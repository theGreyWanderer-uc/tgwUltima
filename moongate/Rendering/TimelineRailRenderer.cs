using Microsoft.Graphics.Canvas.Text;
using Microsoft.Graphics.Canvas.UI.Xaml;
using Moongate.Models;
using Moongate.Services;
using Windows.Foundation;
using Windows.UI;

namespace Moongate.Rendering;

public sealed class TimelineRailRenderer
{
    private const float TopPadding = 44;
    private const float BottomPadding = 44;

    public void Draw(
        CanvasControl sender,
        CanvasDrawEventArgs args,
        DateTimeOffset rangeStart,
        DateTimeOffset rangeEnd,
        IReadOnlyList<CalendarEvent> events,
        DateTimeOffset? selectedDate = null,
        string? selectedEventId = null,
        float railPositionRatio = 0.62f)
    {
        float width = (float)sender.ActualWidth;
        float height = (float)sender.ActualHeight;

        if (width <= 0 || height <= TopPadding + BottomPadding)
        {
            return;
        }

        CalendarRenderTheme theme = CalendarRenderTheme.FromResources();
        Color accent = ThemeService.GetColor("MoongateAccentLightBrush", theme.Today);
        float railX = Math.Clamp(width * railPositionRatio, 48, width - 28);
        float railTop = TopPadding;
        float railBottom = height - BottomPadding;

        args.DrawingSession.DrawLine(railX, railTop, railX, railBottom, WithAlpha(theme.Border, 180), 3);
        args.DrawingSession.DrawLine(railX - 1, railTop, railX - 1, railBottom, WithAlpha(accent, 70), 1);

        DrawTimeTicks(args, rangeStart, rangeEnd, railX, railTop, railBottom, theme);
        DrawTodayMarker(args, rangeStart, rangeEnd, railX, railTop, railBottom, theme);
        DrawEventMarkers(args, rangeStart, rangeEnd, events, selectedEventId, railX, railTop, railBottom, theme);
        DrawSelectedDateMarker(args, selectedDate, selectedEventId, rangeStart, rangeEnd, railX, railTop, railBottom, theme);
    }

    private static void DrawTimeTicks(
        CanvasDrawEventArgs args,
        DateTimeOffset rangeStart,
        DateTimeOffset rangeEnd,
        float railX,
        float railTop,
        float railBottom,
        CalendarRenderTheme theme)
    {
        TimeSpan range = rangeEnd - rangeStart;
        CanvasTextFormat labelFormat = new()
        {
            FontSize = 12,
            HorizontalAlignment = CanvasHorizontalAlignment.Right,
            VerticalAlignment = CanvasVerticalAlignment.Center
        };

        if (range.TotalDays <= 1.1)
        {
            DrawDayTicks(args, rangeStart, rangeEnd, railX, railTop, railBottom, theme, labelFormat);

            return;
        }

        int stepDays = range.TotalDays <= 8
            ? 1
            : range.TotalDays <= 35
                ? 7
                : 14;

        DateTimeOffset firstTick = rangeStart.Date;
        while (firstTick < rangeStart)
        {
            firstTick = firstTick.AddDays(stepDays);
        }

        for (DateTimeOffset tick = firstTick; tick <= rangeEnd; tick = tick.AddDays(stepDays))
        {
            string label = range.TotalDays <= 8
                ? tick.ToString("ddd d")
                : tick.ToString("MMM d");

            DrawTick(args, tick, label, rangeStart, rangeEnd, railX, railTop, railBottom, theme, labelFormat);
        }
    }

    private static void DrawDayTicks(
        CanvasDrawEventArgs args,
        DateTimeOffset rangeStart,
        DateTimeOffset rangeEnd,
        float railX,
        float railTop,
        float railBottom,
        CalendarRenderTheme theme,
        CanvasTextFormat labelFormat)
    {
        List<DateTimeOffset> ticks = [rangeStart];

        DateTimeOffset nextSixHourTick = rangeStart.Date.AddHours(((rangeStart.Hour / 6) + 1) * 6);
        while (nextSixHourTick < rangeEnd)
        {
            ticks.Add(nextSixHourTick);
            nextSixHourTick = nextSixHourTick.AddHours(6);
        }

        ticks.Add(rangeEnd);

        float lastLabelY = float.NegativeInfinity;
        foreach (DateTimeOffset tick in ticks)
        {
            float y = MapDateToY(tick, rangeStart, rangeEnd, railTop, railBottom);
            bool drawLabel = y - lastLabelY >= 30 || tick == rangeStart || tick == rangeEnd;

            DrawTick(
                args,
                tick,
                tick.ToString("htt").ToLowerInvariant(),
                rangeStart,
                rangeEnd,
                railX,
                railTop,
                railBottom,
                theme,
                labelFormat,
                drawLabel);

            if (drawLabel)
            {
                lastLabelY = y;
            }
        }
    }

    private static void DrawTick(
        CanvasDrawEventArgs args,
        DateTimeOffset tick,
        string label,
        DateTimeOffset rangeStart,
        DateTimeOffset rangeEnd,
        float railX,
        float railTop,
        float railBottom,
        CalendarRenderTheme theme,
        CanvasTextFormat labelFormat,
        bool drawLabel = true)
    {
        float y = MapDateToY(tick, rangeStart, rangeEnd, railTop, railBottom);
        args.DrawingSession.DrawLine(railX - 9, y, railX + 9, y, WithAlpha(theme.Border, 210), 1);
        if (drawLabel)
        {
            args.DrawingSession.DrawText(label, new Rect(0, y - 12, railX - 16, 24), theme.MutedText, labelFormat);
        }
    }

    private static void DrawTodayMarker(
        CanvasDrawEventArgs args,
        DateTimeOffset rangeStart,
        DateTimeOffset rangeEnd,
        float railX,
        float railTop,
        float railBottom,
        CalendarRenderTheme theme)
    {
        DateTimeOffset today = DateTimeOffset.Now;
        if (today < rangeStart || today > rangeEnd)
        {
            return;
        }

        float y = MapDateToY(today, rangeStart, rangeEnd, railTop, railBottom);
        args.DrawingSession.FillCircle(railX, y, 10, WithAlpha(theme.Today, 55));
        args.DrawingSession.FillCircle(railX, y, 5, theme.Today);
    }

    private static void DrawEventMarkers(
        CanvasDrawEventArgs args,
        DateTimeOffset rangeStart,
        DateTimeOffset rangeEnd,
        IReadOnlyList<CalendarEvent> events,
        string? selectedEventId,
        float railX,
        float railTop,
        float railBottom,
        CalendarRenderTheme theme)
    {
        foreach (CalendarEvent calendarEvent in events.Where(calendarEvent => calendarEvent.Start >= rangeStart && calendarEvent.Start < rangeEnd))
        {
            float y = MapDateToY(calendarEvent.Start, rangeStart, rangeEnd, railTop, railBottom);
            Color marker = ParseColor(calendarEvent.CategoryColor, theme.EventFill);
            bool isSelected = selectedEventId is not null && calendarEvent.Id == selectedEventId;
            float outerRadius = isSelected ? 13 : 8;
            float innerRadius = isSelected ? 7 : 4.5f;

            args.DrawingSession.FillCircle(railX, y, outerRadius, WithAlpha(marker, isSelected ? (byte)110 : (byte)65));
            args.DrawingSession.FillCircle(railX, y, innerRadius, marker);

            if (isSelected)
            {
                Color accent = ThemeService.GetColor("MoongateAccentLightBrush", theme.Today);
                args.DrawingSession.DrawCircle(railX, y, outerRadius + 2, accent, 2);
            }
        }
    }

    private static void DrawSelectedDateMarker(
        CanvasDrawEventArgs args,
        DateTimeOffset? selectedDate,
        string? selectedEventId,
        DateTimeOffset rangeStart,
        DateTimeOffset rangeEnd,
        float railX,
        float railTop,
        float railBottom,
        CalendarRenderTheme theme)
    {
        if (selectedDate is null || selectedEventId is not null || selectedDate.Value < rangeStart || selectedDate.Value >= rangeEnd)
        {
            return;
        }

        float y = MapDateToY(selectedDate.Value, rangeStart, rangeEnd, railTop, railBottom);
        Color accent = ThemeService.GetColor("MoongateAccentLightBrush", theme.Today);
        args.DrawingSession.FillCircle(railX, y, 13, WithAlpha(accent, 90));
        args.DrawingSession.FillCircle(railX, y, 7, accent);
        args.DrawingSession.DrawCircle(railX, y, 15, theme.Border, 1.5f);
    }

    private static float MapDateToY(
        DateTimeOffset date,
        DateTimeOffset rangeStart,
        DateTimeOffset rangeEnd,
        float railTop,
        float railBottom)
    {
        double total = Math.Max(1, (rangeEnd - rangeStart).TotalSeconds);
        double elapsed = Math.Clamp((date - rangeStart).TotalSeconds, 0, total);
        return railTop + (float)(elapsed / total) * (railBottom - railTop);
    }

    private static Color WithAlpha(Color color, byte alpha)
    {
        return Color.FromArgb(alpha, color.R, color.G, color.B);
    }

    private static Color ParseColor(string color, Color fallback)
    {
        if (string.IsNullOrWhiteSpace(color))
        {
            return fallback;
        }

        string hex = color.Trim().TrimStart('#');
        if (hex.Length == 6)
        {
            hex = "FF" + hex;
        }

        if (hex.Length != 8 || !uint.TryParse(hex, System.Globalization.NumberStyles.HexNumber, null, out uint value))
        {
            return fallback;
        }

        return Color.FromArgb(
            (byte)((value & 0xFF000000) >> 24),
            (byte)((value & 0x00FF0000) >> 16),
            (byte)((value & 0x0000FF00) >> 8),
            (byte)(value & 0x000000FF));
    }
}
