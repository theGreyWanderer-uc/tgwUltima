using Moongate.Models;

namespace Moongate.Services;

public interface ICalendarEventRepository
{
    Task<bool> ExistsAsync();

    Task<IReadOnlyList<CalendarEvent>> LoadAllAsync();

    Task SaveAllAsync(IEnumerable<CalendarEvent> events);

    Task<IReadOnlyList<CalendarEvent>> GetEventsForDateAsync(DateTimeOffset date);

    Task<IReadOnlyList<CalendarEvent>> GetEventsInRangeAsync(DateTimeOffset startInclusive, DateTimeOffset endExclusive);

    Task UpsertAsync(CalendarEvent calendarEvent);

    Task DeleteAsync(string eventId);
}
