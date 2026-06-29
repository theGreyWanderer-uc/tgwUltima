using System.Text.Json;
using Moongate.Models;
using Windows.Storage;

namespace Moongate.Services;

public sealed class JsonCalendarEventRepository : ICalendarEventRepository
{
    private const string EventsFileName = "events.json";
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        WriteIndented = true
    };

    public async Task<bool> ExistsAsync()
    {
        try
        {
            await ApplicationData.Current.LocalFolder.GetFileAsync(EventsFileName);
            return true;
        }
        catch (FileNotFoundException)
        {
            return false;
        }
    }

    public async Task<IReadOnlyList<CalendarEvent>> LoadAllAsync()
    {
        try
        {
            StorageFile file = await ApplicationData.Current.LocalFolder.GetFileAsync(EventsFileName);
            string json = await FileIO.ReadTextAsync(file);
            return JsonSerializer.Deserialize<List<CalendarEvent>>(json, SerializerOptions) ?? [];
        }
        catch (FileNotFoundException)
        {
            return [];
        }
        catch (JsonException)
        {
            return [];
        }
    }

    public async Task SaveAllAsync(IEnumerable<CalendarEvent> events)
    {
        StorageFile file = await ApplicationData.Current.LocalFolder.CreateFileAsync(
            EventsFileName,
            CreationCollisionOption.ReplaceExisting);

        string json = JsonSerializer.Serialize(events.OrderBy(calendarEvent => calendarEvent.Start), SerializerOptions);
        await FileIO.WriteTextAsync(file, json);
    }

    public async Task<IReadOnlyList<CalendarEvent>> GetEventsForDateAsync(DateTimeOffset date)
    {
        DateTimeOffset start = date.Date;
        DateTimeOffset end = start.AddDays(1);
        return await GetEventsInRangeAsync(start, end);
    }

    public async Task<IReadOnlyList<CalendarEvent>> GetEventsInRangeAsync(
        DateTimeOffset startInclusive,
        DateTimeOffset endExclusive)
    {
        IReadOnlyList<CalendarEvent> events = await LoadAllAsync();
        return events
            .Where(calendarEvent => calendarEvent.Start < endExclusive && calendarEvent.End > startInclusive)
            .OrderBy(calendarEvent => calendarEvent.Start)
            .ThenBy(calendarEvent => calendarEvent.Title)
            .ToList();
    }

    public async Task UpsertAsync(CalendarEvent calendarEvent)
    {
        List<CalendarEvent> events = [.. await LoadAllAsync()];
        int existingIndex = events.FindIndex(existingEvent => existingEvent.Id == calendarEvent.Id);

        if (existingIndex >= 0)
        {
            events[existingIndex] = calendarEvent;
        }
        else
        {
            events.Add(calendarEvent);
        }

        await SaveAllAsync(events);
    }

    public async Task DeleteAsync(string eventId)
    {
        List<CalendarEvent> events = [.. await LoadAllAsync()];
        events.RemoveAll(calendarEvent => calendarEvent.Id == eventId);
        await SaveAllAsync(events);
    }
}
