using Microsoft.Graphics.Canvas.Text;
using Microsoft.Graphics.Canvas.UI.Xaml;
using Microsoft.UI.Text;
using Moongate.Models;
using Moongate.Services;
using Windows.Foundation;
using Windows.UI;

namespace Moongate.Rendering;

public sealed class MonthCalendarRenderer
{
    private const int CalendarColumns = 7;
    private const int CalendarRows = 6;
    private const float WeekdayHeaderHeight = 38;
    private readonly List<MonthCalendarCell> _cells = [];

    public IReadOnlyList<MonthCalendarCell> Cells => _cells;

    public DateTimeOffset? HitTest(Point point)
    {
        foreach (MonthCalendarCell cell in _cells)
        {
            if (cell.Bounds.Contains(point))
            {
                return cell.Date;
            }
        }

        return null;
    }

    public void Draw(
        CanvasControl sender,
        CanvasDrawEventArgs args,
        DateTimeOffset displayMonth,
        DateTimeOffset selectedDate,
        IReadOnlyList<CalendarEvent> events)
    {
        float width = (float)sender.ActualWidth;
        float height = (float)sender.ActualHeight;

        if (width <= 0 || height <= WeekdayHeaderHeight)
        {
            return;
        }

        _cells.Clear();
        DrawCalendarSurface(args, width, height, displayMonth, selectedDate, events);
    }

    private void DrawCalendarSurface(
        CanvasDrawEventArgs args,
        float width,
        float height,
        DateTimeOffset displayMonth,
        DateTimeOffset selectedDate,
        IReadOnlyList<CalendarEvent> events)
    {
        string[] weekdayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
        float cellWidth = width / CalendarColumns;
        float cellHeight = (height - WeekdayHeaderHeight) / CalendarRows;
        DateTimeOffset firstVisibleDate = displayMonth.AddDays(-(int)displayMonth.DayOfWeek);
        CalendarRenderTheme theme = CalendarRenderTheme.FromResources();

        CanvasTextFormat weekdayFormat = new()
        {
            FontSize = 14,
            FontWeight = FontWeights.SemiBold,
            HorizontalAlignment = CanvasHorizontalAlignment.Center,
            VerticalAlignment = CanvasVerticalAlignment.Center
        };

        CanvasTextFormat dayNumberFormat = new()
        {
            FontSize = 20,
            FontWeight = FontWeights.SemiBold,
            HorizontalAlignment = CanvasHorizontalAlignment.Left,
            VerticalAlignment = CanvasVerticalAlignment.Top
        };

        CanvasTextFormat eventFormat = new()
        {
            FontSize = 12,
            HorizontalAlignment = CanvasHorizontalAlignment.Left,
            VerticalAlignment = CanvasVerticalAlignment.Center,
            WordWrapping = CanvasWordWrapping.NoWrap
        };

        args.DrawingSession.Clear(theme.Surface);

        for (int column = 0; column < CalendarColumns; column++)
        {
            Rect headerRect = new(column * cellWidth, 0, cellWidth, WeekdayHeaderHeight);
            args.DrawingSession.FillRectangle(headerRect, theme.Header);
            args.DrawingSession.DrawText(
                weekdayLabels[column],
                headerRect,
                column == 0 ? theme.SundayText : theme.Text,
                weekdayFormat);
        }

        for (int index = 0; index < CalendarColumns * CalendarRows; index++)
        {
            int row = index / CalendarColumns;
            int column = index % CalendarColumns;
            DateTimeOffset date = firstVisibleDate.AddDays(index);
            Rect bounds = new(column * cellWidth, WeekdayHeaderHeight + row * cellHeight, cellWidth, cellHeight);
            bool isInDisplayMonth = date.Month == displayMonth.Month;
            bool isSelected = date.Date == selectedDate.Date;
            bool isToday = date.Date == DateTimeOffset.Now.Date;

            _cells.Add(new MonthCalendarCell(date.Date, bounds));

            args.DrawingSession.FillRectangle(
                bounds,
                isSelected ? theme.Selected : isInDisplayMonth ? theme.Surface : theme.OutOfMonth);
            args.DrawingSession.DrawRectangle(bounds, theme.Border, 1);

            Color dayColor = !isInDisplayMonth
                ? theme.MutedText
                : column == 0
                    ? theme.SundayText
                    : theme.Text;

            args.DrawingSession.DrawText(
                date.Day.ToString(),
                new Rect(bounds.X + 10, bounds.Y + 8, bounds.Width - 20, 28),
                dayColor,
                dayNumberFormat);

            if (isToday)
            {
                args.DrawingSession.DrawRoundedRectangle(
                    (float)bounds.X + 6,
                    (float)bounds.Y + 6,
                    (float)bounds.Width - 12,
                    (float)bounds.Height - 12,
                    6,
                    6,
                    theme.Today,
                    2);
            }

            DrawEventsForDate(args, date, bounds, events, theme, eventFormat);
        }
    }

    private static void DrawEventsForDate(
        CanvasDrawEventArgs args,
        DateTimeOffset date,
        Rect bounds,
        IReadOnlyList<CalendarEvent> events,
        CalendarRenderTheme theme,
        CanvasTextFormat eventFormat)
    {
        List<CalendarEvent> dayEvents = events
            .Where(calendarEvent => calendarEvent.Start.Date == date.Date)
            .OrderBy(calendarEvent => calendarEvent.Start)
            .Take(3)
            .ToList();

        float eventTop = (float)bounds.Y + 42;
        float eventHeight = 20;
        float eventGap = 5;

        for (int index = 0; index < dayEvents.Count; index++)
        {
            CalendarEvent calendarEvent = dayEvents[index];
            float y = eventTop + index * (eventHeight + eventGap);

            if (y + eventHeight > bounds.Bottom - 10)
            {
                break;
            }

            Rect eventRect = new(bounds.X + 10, y, Math.Max(20, bounds.Width - 20), eventHeight);
            Color eventFill = ParseColor(calendarEvent.CategoryColor, theme.EventFill);
            args.DrawingSession.FillRoundedRectangle(eventRect, 4, 4, eventFill);
            args.DrawingSession.DrawText($" {calendarEvent.TimeLabel}  {calendarEvent.Title}", eventRect, theme.EventText, eventFormat);
        }

        int totalCount = events.Count(calendarEvent => calendarEvent.Start.Date == date.Date);
        if (totalCount > dayEvents.Count)
        {
            args.DrawingSession.DrawText(
                $"+{totalCount - dayEvents.Count} more",
                new Rect(bounds.X + 10, bounds.Bottom - 28, bounds.Width - 20, 18),
                theme.MutedText,
                eventFormat);
        }
    }

    private static Color ParseColor(string color, Color fallback)
    {
        if (color.Length != 9 || color[0] != '#')
        {
            return fallback;
        }

        try
        {
            return Color.FromArgb(
                Convert.ToByte(color[1..3], 16),
                Convert.ToByte(color[3..5], 16),
                Convert.ToByte(color[5..7], 16),
                Convert.ToByte(color[7..9], 16));
        }
        catch (FormatException)
        {
            return fallback;
        }
    }
}
