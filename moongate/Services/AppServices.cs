using Moongate.Commands;

namespace Moongate.Services;

public static class AppServices
{
    public static AppCommandRegistry CommandRegistry { get; } = AppCommandRegistry.CreateDefault();

    public static ThemeService ThemeService { get; } = new();

    public static ICalendarEventRepository EventRepository { get; } = new JsonCalendarEventRepository();
}
