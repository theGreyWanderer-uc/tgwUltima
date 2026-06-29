namespace Moongate.Services;

public static class AppServices
{
    public static ThemeService ThemeService { get; } = new();

    public static ICalendarEventRepository EventRepository { get; } = new JsonCalendarEventRepository();
}
