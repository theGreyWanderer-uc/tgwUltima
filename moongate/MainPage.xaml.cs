using System.Collections.ObjectModel;
using Microsoft.Graphics.Canvas.UI.Xaml;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Moongate.Models;
using Moongate.Rendering;
using Moongate.Services;
using Windows.Foundation;
using Windows.UI;

namespace Moongate;

public sealed partial class MainPage : Page
{
    private readonly MonthCalendarRenderer _calendarRenderer = new();
    private readonly ICalendarEventRepository _eventRepository = AppServices.EventRepository;
    private readonly ThemeService _themeService = AppServices.ThemeService;
    private DateTimeOffset _displayMonth;
    private List<CalendarEvent> _events = [];
    private DateTimeOffset _selectedDate;

    public ObservableCollection<CalendarEvent> VisibleEvents { get; } = [];

    public MainPage()
    {
        InitializeComponent();

        DateTimeOffset today = DateTimeOffset.Now.Date;
        _selectedDate = today;
        _displayMonth = GetMonthStart(today);

        Loaded += MainPage_Loaded;
        _themeService.ThemeChanged += ThemeService_ThemeChanged;
        _themeService.ApplyStoredTheme();
    }

    private async void MainPage_Loaded(object sender, RoutedEventArgs e)
    {
        if (!await _eventRepository.ExistsAsync())
        {
            _events = CreateStarterEvents(DateTimeOffset.Now.Date);
            await _eventRepository.SaveAllAsync(_events);
        }
        else
        {
            _events = [.. await _eventRepository.LoadAllAsync()];
        }

        SelectDate(DateTimeOffset.Now.Date, updateDisplayMonth: true);
    }

    private void ThemeService_ThemeChanged(object? sender, EventArgs e)
    {
        CalendarCanvas.Invalidate();
    }

    private void TodayButton_Click(object sender, RoutedEventArgs e)
    {
        SelectDate(DateTimeOffset.Now.Date, updateDisplayMonth: true);
    }

    private void PreviousMonthButton_Click(object sender, RoutedEventArgs e)
    {
        _displayMonth = _displayMonth.AddMonths(-1);
        UpdateMonthTitle();
        CalendarCanvas.Invalidate();
    }

    private void NextMonthButton_Click(object sender, RoutedEventArgs e)
    {
        _displayMonth = _displayMonth.AddMonths(1);
        UpdateMonthTitle();
        CalendarCanvas.Invalidate();
    }

    private async void AddEventButton_Click(object sender, RoutedEventArgs e)
    {
        await ShowEventEditorAsync(existingEvent: null);
    }

    private async void AgendaList_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is CalendarEvent calendarEvent)
        {
            await ShowEventEditorAsync(calendarEvent);
        }
    }

    private async Task ShowEventEditorAsync(CalendarEvent? existingEvent)
    {
        EventEditorResult? result = await ShowEventDialogAsync(existingEvent);

        if (result is null)
        {
            return;
        }

        if (result.Action == EventEditorAction.Delete && existingEvent is not null)
        {
            await _eventRepository.DeleteAsync(existingEvent.Id);
            _events.RemoveAll(calendarEvent => calendarEvent.Id == existingEvent.Id);
        }
        else if (result.Event is not null)
        {
            await _eventRepository.UpsertAsync(result.Event);
            int existingIndex = _events.FindIndex(calendarEvent => calendarEvent.Id == result.Event.Id);

            if (existingIndex >= 0)
            {
                _events[existingIndex] = result.Event;
            }
            else
            {
                _events.Add(result.Event);
            }
        }

        _events = [.. _events.OrderBy(calendarEvent => calendarEvent.Start)];
        SelectDate(_selectedDate, updateDisplayMonth: false);
    }

    private async Task<EventEditorResult?> ShowEventDialogAsync(CalendarEvent? existingEvent)
    {
        bool isEditing = existingEvent is not null;
        DateTimeOffset eventDate = existingEvent?.Start.Date ?? _selectedDate.Date;
        EventCategory selectedCategory = EventCategories.GetById(existingEvent?.CategoryId);

        TextBlock errorText = new()
        {
            Foreground = ThemeService.GetBrush("MoongateDangerBrush", Color.FromArgb(255, 196, 43, 28)),
            Text = "Enter a title and make sure the end time is after the start time.",
            Visibility = Visibility.Collapsed,
            TextWrapping = TextWrapping.Wrap
        };

        TextBox titleBox = new()
        {
            Header = "Title",
            PlaceholderText = "Event title",
            Text = existingEvent?.Title ?? string.Empty
        };

        DatePicker datePicker = new()
        {
            Header = "Date",
            Date = eventDate
        };

        TimePicker startTimePicker = new()
        {
            Header = "Start",
            Time = existingEvent?.Start.TimeOfDay ?? new TimeSpan(9, 0, 0)
        };

        TimePicker endTimePicker = new()
        {
            Header = "End",
            Time = existingEvent?.End.TimeOfDay ?? new TimeSpan(10, 0, 0)
        };

        ComboBox categoryBox = new()
        {
            Header = "Category",
            ItemsSource = EventCategories.All,
            DisplayMemberPath = nameof(EventCategory.DisplayName),
            SelectedValuePath = nameof(EventCategory.Id),
            SelectedValue = selectedCategory.Id
        };

        TextBox locationBox = new()
        {
            Header = "Location",
            PlaceholderText = "Optional",
            Text = existingEvent?.Location ?? string.Empty
        };

        TextBox notesBox = new()
        {
            Header = "Notes",
            AcceptsReturn = true,
            Height = 92,
            TextWrapping = TextWrapping.Wrap,
            Text = existingEvent?.Notes ?? string.Empty
        };

        Grid timeGrid = new()
        {
            ColumnSpacing = 12,
            ColumnDefinitions =
            {
                new ColumnDefinition(),
                new ColumnDefinition()
            }
        };
        Grid.SetColumn(endTimePicker, 1);
        timeGrid.Children.Add(startTimePicker);
        timeGrid.Children.Add(endTimePicker);

        StackPanel content = new()
        {
            Spacing = 12,
            Children =
            {
                errorText,
                titleBox,
                datePicker,
                timeGrid,
                categoryBox,
                locationBox,
                notesBox
            }
        };

        ContentDialog dialog = new()
        {
            XamlRoot = XamlRoot,
            Title = isEditing ? "Edit event" : "Add event",
            Content = content,
            PrimaryButtonText = isEditing ? "Save" : "Add",
            SecondaryButtonText = isEditing ? "Delete" : string.Empty,
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary
        };

        dialog.PrimaryButtonClick += (_, args) =>
        {
            if (!IsValidEventInput(titleBox.Text, startTimePicker.Time, endTimePicker.Time))
            {
                errorText.Visibility = Visibility.Visible;
                args.Cancel = true;
            }
        };

        ContentDialogResult dialogResult = await dialog.ShowAsync();

        if (dialogResult == ContentDialogResult.None)
        {
            return null;
        }

        if (dialogResult == ContentDialogResult.Secondary)
        {
            return new EventEditorResult(EventEditorAction.Delete, existingEvent);
        }

        DateTimeOffset start = datePicker.Date.Date + startTimePicker.Time;
        DateTimeOffset end = datePicker.Date.Date + endTimePicker.Time;
        EventCategory category = EventCategories.GetById(categoryBox.SelectedValue as string);

        CalendarEvent calendarEvent = new()
        {
            Id = existingEvent?.Id ?? Guid.NewGuid().ToString("N"),
            Title = titleBox.Text.Trim(),
            Start = start,
            End = end,
            Location = locationBox.Text.Trim(),
            Notes = notesBox.Text.Trim(),
            CategoryId = category.Id,
            CategoryColor = category.Color
        };

        return new EventEditorResult(EventEditorAction.Upsert, calendarEvent);
    }

    private static bool IsValidEventInput(string title, TimeSpan start, TimeSpan end)
    {
        return !string.IsNullOrWhiteSpace(title) && end > start;
    }

    private void CalendarCanvas_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        Point point = e.GetCurrentPoint(CalendarCanvas).Position;
        DateTimeOffset? date = _calendarRenderer.HitTest(point);

        if (date is not null)
        {
            SelectDate(date.Value, updateDisplayMonth: date.Value.Month != _displayMonth.Month);
            e.Handled = true;
        }
    }

    private void SelectDate(DateTimeOffset date, bool updateDisplayMonth)
    {
        _selectedDate = date.Date;

        if (updateDisplayMonth)
        {
            _displayMonth = GetMonthStart(date);
        }

        UpdateMonthTitle();
        UpdateAgenda(_selectedDate);
        CalendarCanvas.Invalidate();
    }

    private void UpdateMonthTitle()
    {
        MonthTitle.Text = _displayMonth.ToString("MMMM yyyy");
    }

    private void UpdateAgenda(DateTimeOffset date)
    {
        DateTimeOffset selectedDate = date.Date;

        SelectedDateTitle.Text = selectedDate.ToString("dddd, MMMM d");
        SelectedDateSubtitle.Text = selectedDate.Date == DateTimeOffset.Now.Date
            ? "Today"
            : selectedDate.ToString("yyyy");

        VisibleEvents.Clear();

        foreach (CalendarEvent calendarEvent in _events
            .Where(calendarEvent => calendarEvent.Start.Date == selectedDate.Date)
            .OrderBy(calendarEvent => calendarEvent.Start))
        {
            VisibleEvents.Add(calendarEvent);
        }

        EmptyAgendaText.Visibility = VisibleEvents.Count == 0
            ? Visibility.Visible
            : Visibility.Collapsed;
    }

    private void CalendarCanvas_Draw(CanvasControl sender, CanvasDrawEventArgs args)
    {
        _calendarRenderer.Draw(sender, args, _displayMonth, _selectedDate, _events);
    }

    private void Page_Unloaded(object sender, RoutedEventArgs e)
    {
        _themeService.ThemeChanged -= ThemeService_ThemeChanged;
        CalendarCanvas.RemoveFromVisualTree();
        CalendarCanvas = null!;
    }

    private static DateTimeOffset GetMonthStart(DateTimeOffset date)
    {
        return new DateTimeOffset(date.Year, date.Month, 1, 0, 0, 0, date.Offset);
    }

    private static List<CalendarEvent> CreateStarterEvents(DateTimeOffset today)
    {
        return
        [
            CreateStarterEvent("Morning planning", today.AddHours(9), today.AddHours(9.5), "Desk", "personal"),
            CreateStarterEvent("Design review", today.AddHours(11), today.AddHours(12), "Studio", "work"),
            CreateStarterEvent("Calendar model sketch", today.AddDays(1).AddHours(10), today.AddDays(1).AddHours(11), "Moongate", "focus"),
            CreateStarterEvent("Reminder research", today.AddDays(2).AddHours(14), today.AddDays(2).AddHours(15), "Windows App SDK", "reminder"),
            CreateStarterEvent("Win2D prototype pass", today.AddDays(4).AddHours(13), today.AddDays(4).AddHours(14.5), "Rendering", "focus"),
            CreateStarterEvent("Quiet admin block", today.AddDays(7).AddHours(9), today.AddDays(7).AddHours(10), "Home", "personal")
        ];
    }

    private static CalendarEvent CreateStarterEvent(
        string title,
        DateTimeOffset start,
        DateTimeOffset end,
        string location,
        string categoryId)
    {
        EventCategory category = EventCategories.GetById(categoryId);
        return new CalendarEvent
        {
            Title = title,
            Start = start,
            End = end,
            Location = location,
            CategoryId = category.Id,
            CategoryColor = category.Color
        };
    }

    private sealed record EventEditorResult(EventEditorAction Action, CalendarEvent? Event);

    private enum EventEditorAction
    {
        Upsert,
        Delete
    }
}
