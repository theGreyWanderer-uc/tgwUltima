namespace Moongate.Models;

public sealed class CalendarEvent
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");

    public string Title { get; set; } = string.Empty;

    public DateTimeOffset Start { get; set; }

    public DateTimeOffset End { get; set; }

    public string Location { get; set; } = string.Empty;

    public string Notes { get; set; } = string.Empty;

    public string CategoryId { get; set; } = EventCategories.DefaultId;

    public string CategoryColor { get; set; } = EventCategories.DefaultColor;

    public string TimeLabel => $"{Start:h:mm tt}";

    public string RangeLabel => $"{Start:h:mm tt} - {End:h:mm tt}";

    public string DateLabel => Start.ToString("ddd, MMM d");

    public string DetailLabel
    {
        get
        {
            string location = string.IsNullOrWhiteSpace(Location) ? "No location" : Location;
            return $"{RangeLabel} | {location}";
        }
    }
}
