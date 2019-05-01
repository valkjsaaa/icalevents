"""
Parse iCal data to Events.
"""
# for UID generation
from random import randint
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrule, rruleset, rrulestr
from dateutil.tz import UTC, gettz

from icalendar import Calendar
from icalendar.prop import vDDDLists
from pytz import timezone

def now():
    """
    Get current time.

    :return: now as datetime with timezone
    """
    return datetime.now(UTC)


class Event:
    """
    Represents one event (occurrence in case of reoccurring events).
    """

    def __init__(self):
        """
        Create a new event occurrence.
        """
        self.uid = -1
        self.summary = None
        self.description = None
        self.start = None
        self.end = None
        self.all_day = True
        self.recurring = False
        self.location = None

    def time_left(self, time=None):
        """
        timedelta form now to event.

        :return: timedelta from now
        """
        time = time or now()
        return self.start - time

    def __lt__(self, other):
        """
        Events are sorted by start time by default.

        :param other: other event
        :return: True if start of this event is smaller than other
        """
        if not other or not isinstance(other, Event):
            raise ValueError('Only events can be compared with each other! Other is %s' % type(other))
        else:
            return self.start < other.start

    def __str__(self):
        n = now()

        # compute time delta description
        if not self.all_day:
            if self.end > n > self.start:
                # event is now
                delta = "now"
            elif self.start > n:
                # event is a future event
                if self.time_left().days > 0:
                    delta = "%s days left" % self.time_left().days
                else:
                    hours = self.time_left().seconds / (60 * 60)
                    delta = "%.1f hours left" % hours
            else:
                # event is over
                delta = "ended"
        else:
            if self.end > n > self.start:
                delta = "today"
            elif self.start > n:
                delta = "%s days left" % self.time_left().days
            else:
                delta = "ended"

        return "%s: %s (%s)" % (self.start, self.summary, delta)

    def copy_to(self, new_start=None, uid=None):
        """
        Create a new event equal to this with new start date.

        :param new_start: new start date
        :param uid: UID of new event
        :return: new event
        """
        if not new_start:
            new_start = self.start

        if not uid:
            uid = "%s_%d" % (self.uid, randint(0, 1000000))

        ne = Event()
        ne.summary = self.summary
        ne.description = self.description
        ne.start = new_start
        
        if self.end:
            duration = self.end - self.start
            ne.end = (new_start + duration)

        ne.all_day = self.all_day
        ne.recurring = self.recurring
        ne.location = self.location
        ne.uid = uid

        return ne


def create_event(component, tz=UTC):
    """
    Create an event from its iCal representation.

    :param component: iCal component
    :param tz: timezone for start and end times
    :return: event
    """

    event = Event()

    event.start = normalize(component.get('dtstart').dt, tz=tz)
    
    if component.get('dtend'):
        event.end = normalize(component.get('dtend').dt, tz=tz)
    elif component.get('duration'): # compute implicit end as start + duration
        event.end = event.start + component.get('duration').dt
    else: # compute implicit end as start + 0
        event.end = event.start
    
    try:
        event.summary = str(component.get('summary'))
    except UnicodeEncodeError as e:
        event.summary = str(component.get('summary').encode('utf-8'))
    try:
        event.description = str(component.get('description'))
    except UnicodeEncodeError as e:
        event.description = str(component.get('description').encode('utf-8'))
    event.all_day = type(component.get('dtstart').dt) is date
    if component.get('rrule'):
        event.recurring = True
    try:
        event.location = str(component.get('location'))
    except UnicodeEncodeError as e:
        event.location = str(component.get('location').encode('utf-8'))

    if component.get('attendee'):
        event.attendee = component.get('attendee')
        if type(event.attendee) is list:
            temp = []
            for a in event.attendee:
                temp.append(a.encode('utf-8').decode('ascii'))
            event.attendee = temp
        else:
            event.attendee = event.attendee.encode('utf-8').decode('ascii')

    if component.get('uid'):
        event.uid = component.get('uid').encode('utf-8').decode('ascii')

    if component.get('organizer'):
        event.organizer = component.get('organizer').encode('utf-8').decode('ascii')

    return event


def normalize(dt, tz=UTC, replace=False):
    """
    Convert date or datetime to datetime with timezone.

    :param dt: date to normalize
    :param tz: the normalized date's timezone
    :return: date as datetime with timezone
    """
    if type(dt) is date:
        dt = dt + relativedelta(hour=0)
    elif type(dt) is datetime:
        pass
    else:
        raise ValueError("unknown type %s" % type(dt))

    if dt.tzinfo:
        # Per https://github.com/irgangla/icalevents/issues/12#issuecomment-456121570
        if replace:
            dt = dt.astimezone(tz)
        else:
            pass
    else:
        dt = dt.replace(tzinfo=tz)

    return dt


def parse_events(content, start=None, end=None, default_span=timedelta(days=7)):
    """
    Query the events occurring in a given time range.

    :param content: iCal URL/file content as String
    :param start: start date for search, default today
    :param end: end date for search
    :param default_span: default query length (one week)
    :return: events as list
    """
    if not start:
        start = now()

    if not end:
        end = start + default_span

    if not content:
        raise ValueError('Content is invalid!')

    calendar = Calendar.from_ical(content)

    # Keep track of the timezones defined in the calendar
    timezones = {}
    for c in calendar.walk('VTIMEZONE'):
        name = str(c['TZID'])
        timezones[name] = c.to_tz()

    # If there's exactly one timezone in the file,
    # assume it applies globally, otherwise UTC
    if len(timezones) == 1:
        cal_tz = gettz(list(timezones)[0])
    else:
        cal_tz = UTC

    start = normalize(start, cal_tz)
    end = normalize(end, cal_tz)

    found = []

    # Skip dates that are stored as exceptions.
    exceptions = {}
    for component in calendar.walk():
        if component.name == "VEVENT":
            e = create_event(component)

            if ('EXDATE' in component):
                # Deal with the fact that sometimes it's a list and
                # sometimes it's a singleton
                exlist = []
                if isinstance(component['EXDATE'], list):
                    exlist = component['EXDATE']
                else:
                    exlist.append(component['EXDATE'])
                for ex in exlist:
                    exdate = ex.to_ical().decode("UTF-8")
                    exceptions[exdate[0:8]] = exdate

            # Attempt to work out what timezone is used for the start
            # and end times. If the timezone is defined in the calendar,
            # use it; otherwise, attempt to load the rules from pytz.
            start_tz = None
            end_tz = None

            # Ignore all-day apointments, they aren't really in a timezone.
            if not e.all_day:
                if e.start.tzinfo != UTC:
                    if str(e.start.tzinfo) in timezones:
                        start_tz = timezones[str(e.start.tzinfo)]
                    else:
                        try:
                            start_tz = timezone(str(e.start.tzinfo))
                        except:
                            pass

                if e.end.tzinfo != UTC:
                    if str(e.end.tzinfo) in timezones:
                        end_tz = timezones[str(e.end.tzinfo)]
                    else:
                        try:
                            end_tz = timezone(str(e.end.tzinfo))
                        except:
                            pass

            duration = e.end - e.start
            if e.recurring:
                # Unfold recurring events according to their rrule
                rule = parse_rrule(component, cal_tz)
                dur = e.end - e.start
                for dt in rule.between(start - dur, end, inc=True):
                    if start_tz is None:
                        # Shrug. If we coudln't work out the timezone, it is what it is.
                        ecopy = e.copy_to(dt, e.uid)
                    else:
                        # Recompute the start time in the current timezone *on* the
                        # date of *this* occurrence. This handles the case where the
                        # recurrence has crossed over the daylight savings time boundary.
                        naive = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
                        dtstart = start_tz.localize(naive)

                        ecopy = e.copy_to(dtstart, e.uid)

                        # We're effectively looping over the start time, we might need
                        # to adjust the end time too, but don't have it's recurred value.
                        # Make sure it's adjusted by constructing it from the meeting
                        # duration. Pro: it'll be right. Con: if it was in a different
                        # timezone from the start time, we'll have lost that.
                        ecopy.end = dtstart + duration

                    exdate = "%04d%02d%02d" % (ecopy.start.year, ecopy.start.month, ecopy.start.day)
                    if exdate not in exceptions:
                        found.append(ecopy)
            elif e.end >= start and e.start <= end:
                exdate = "%04d%02d%02d" % (e.start.year, e.start.month, e.start.day)
                if exdate not in exceptions:
                    found.append(e)
    return found


def parse_rrule(component, tz=UTC):
    """
    Extract a dateutil.rrule object from an icalendar component. Also includes
    the component's dtstart and exdate properties. The rdate and exrule
    properties are not yet supported.
    
    :param component: icalendar component
    :param tz: timezone for DST handling
    :return: extracted rrule or rruleset
    """
    if component.get('rrule'):
        # component['rrule'] can be both a scalar and a list
        rrules = component['rrule']
        if not isinstance(rrules, list):
            rrules = [rrules]

        # Since DTSTART are always made timezone aware, UNTIL with no tzinfo
        # must be converted to UTC.
        for rule in rrules:
            until = rule.get("until")
            for idx, dt in enumerate(until or []):
                if not hasattr(dt, 'tzinfo'):
                    until[idx] = normalize(normalize(dt, tz=tz), tz=UTC)

        # Parse the rrules, might return a rruleset instance, instead of rrule
        rule = rrulestr('\n'.join(x.to_ical().decode() for x in rrules), dtstart=normalize(component['dtstart'].dt, tz=tz, replace=True))
        
        if component.get('exdate'):
            # Make sure, to work with a rruleset
            if isinstance(rule, rrule):
                rules = rruleset()
                rules.rrule(rule)
                rule = rules
            
            # Add exdates to the rruleset
            for exd in extract_exdates(component):
                rule.exdate(exd)
        
        #TODO: What about rdates and exrules?
        
    # You really want an rrule for a component without rrule? Here you are.
    else:
        rule = rruleset()
        rule.rdate(normalize(component['dtstart'].dt, tz=tz))
    
    return rule


def extract_exdates(component):
    """
    Compile a list of all exception dates stored with a component.
    
    :param component: icalendar iCal component
    :return: list of exception dates
    """
    dates = []

    exd_prop = component.get('exdate')
    if exd_prop:
        if isinstance(exd_prop, list): # In case there is more than one exdate property
            for exd_list in exd_prop:
                dates.extend(normalize(exd.dt) for exd in exd_list.dts)
        elif isinstance(exd_prop, vDDDLists):
            dates.extend(normalize(exd.dt) for exd in exd_prop.dts)

    return dates

