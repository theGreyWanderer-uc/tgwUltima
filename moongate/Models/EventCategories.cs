namespace Moongate.Models;

public static class EventCategories
{
    public const string DefaultId = "personal";
    public const string DefaultColor = "#FF6A9E4A";

    public static IReadOnlyList<EventCategory> All { get; } =
    [
        new() { Id = DefaultId, DisplayName = "Personal", Color = DefaultColor },
        new() { Id = "work", DisplayName = "Work", Color = "#FF2D8B8B" },
        new() { Id = "focus", DisplayName = "Focus", Color = "#FF4A6FA5" },
        new() { Id = "travel", DisplayName = "Travel", Color = "#FFE76F51" },
        new() { Id = "health", DisplayName = "Health", Color = "#FFB87D6D" },
        new() { Id = "reminder", DisplayName = "Reminder", Color = "#FFB7472A" }
    ];

    public static EventCategory GetById(string? id)
    {
        return All.FirstOrDefault(category => category.Id == id) ?? All[0];
    }
}
