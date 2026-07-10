using Windows.UI;

namespace Moongate.Services;

public sealed class CalendarRenderTheme
{
    public Color Surface { get; private init; }

    public Color Header { get; private init; }

    public Color Border { get; private init; }

    public Color OutOfMonth { get; private init; }

    public Color Selected { get; private init; }

    public Color Today { get; private init; }

    public Color Text { get; private init; }

    public Color MutedText { get; private init; }

    public Color SundayText { get; private init; }

    public Color EventFill { get; private init; }

    public Color EventText { get; private init; }

    public static CalendarRenderTheme FromResources()
    {
        return new CalendarRenderTheme
        {
            Surface = ThemeService.GetColor("MoongateCalendarSurfaceBrush", Color.FromArgb(255, 250, 250, 250)),
            Header = ThemeService.GetColor("MoongateCalendarHeaderBrush", Color.FromArgb(255, 236, 239, 243)),
            Border = ThemeService.GetColor("MoongatePanelBorderBrush", Color.FromArgb(255, 136, 144, 154)),
            OutOfMonth = ThemeService.GetColor("MoongateCalendarOutOfMonthBrush", Color.FromArgb(255, 242, 244, 247)),
            Selected = ThemeService.GetColor("MoongateCalendarSelectedBrush", Color.FromArgb(255, 218, 232, 255)),
            Today = ThemeService.GetColor("MoongateCalendarTodayBrush", Color.FromArgb(255, 194, 48, 39)),
            Text = ThemeService.GetColor("MoongateTextBrush", Color.FromArgb(255, 24, 28, 34)),
            MutedText = ThemeService.GetColor("MoongateMutedTextBrush", Color.FromArgb(255, 106, 113, 124)),
            SundayText = ThemeService.GetColor("MoongateCalendarSundayBrush", Color.FromArgb(255, 171, 43, 37)),
            EventFill = ThemeService.GetColor("MoongateCalendarEventBrush", Color.FromArgb(255, 16, 115, 103)),
            EventText = ThemeService.GetColor("MoongateInverseTextBrush", Color.FromArgb(255, 255, 255, 255))
        };
    }
}
