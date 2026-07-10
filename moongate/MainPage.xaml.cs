using System.Collections.ObjectModel;
using Microsoft.Graphics.Canvas.UI.Xaml;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Moongate.Commands;
using Moongate.Models;
using Moongate.Rendering;
using Moongate.Services;
using Windows.Foundation;
using Windows.UI;

namespace Moongate;

public sealed partial class MainPage : Page
{
    private const int TimelineVisibleDays = 2;
    private const double TimelineCardHeight = 82;
    private const double TimelinePanePadding = 12;
    private const double TimelineCardGap = 12;
    private const double TimelineMinAnimationMilliseconds = 500;
    private const double TimelineMaxAnimationMilliseconds = 750;
    private const double TimelineTravelDaysPerSecond = 4;
    private static readonly TimeSpan TimelineVisibleRange = TimeSpan.FromDays(TimelineVisibleDays);

    private readonly AppCommandRegistry _commands = AppServices.CommandRegistry;
    private readonly TimelineRailRenderer _timelineRenderer = new();
    private readonly MonthCalendarRenderer _calendarRenderer = new();
    private readonly ICalendarEventRepository _eventRepository = AppServices.EventRepository;
    private readonly ThemeService _themeService = AppServices.ThemeService;
    private readonly DispatcherTimer _timelineCardClickTimer = new()
    {
        Interval = TimeSpan.FromMilliseconds(400)
    };
    private readonly Dictionary<string, TimelineCardView> _timelineCardViews = [];
    private readonly List<IDisposable> _commandRegistrations = [];
    private Border? _emptyTimelineCard;
    private DateTimeOffset _displayMonth;
    private List<CalendarEvent> _events = [];
    private string? _pendingTimelineCardSelectionId;
    private string? _focusedEventId;
    private bool _isEventEditorOpen;
    private DateTimeOffset _selectedDate;
    private DateTimeOffset _timelineCursor;
    private DateTimeOffset _timelineRangeStart;
    private DateTimeOffset _timelineRangeEnd;
    private DateTimeOffset _timelineAnimationFromStart;
    private DateTimeOffset _timelineAnimationFromEnd;
    private DateTimeOffset _timelineAnimationToStart;
    private DateTimeOffset _timelineAnimationToEnd;
    private TimeSpan _timelineAnimationDuration;
    private TimeSpan? _timelineAnimationStartTime;
    private bool _isTimelineAnimationRunning;

    public MainPage()
    {
        InitializeComponent();

        DateTimeOffset today = DateTimeOffset.Now.Date;
        _selectedDate = today;
        _timelineCursor = GetDefaultTimelinePosition(today);
        _displayMonth = GetMonthStart(today);
        SetTimelineRangeToCursor();

        Loaded += MainPage_Loaded;
        _timelineCardClickTimer.Tick += TimelineCardClickTimer_Tick;
        _themeService.ThemeChanged += ThemeService_ThemeChanged;
        _themeService.ApplyStoredTheme();
    }

    private async void MainPage_Loaded(object sender, RoutedEventArgs e)
    {
        RegisterCommandHandlers();

        if (!await _eventRepository.ExistsAsync())
        {
            _events = CreateStarterEvents(DateTimeOffset.Now.Date);
            await _eventRepository.SaveAllAsync(_events);
        }
        else
        {
            _events = [.. await _eventRepository.LoadAllAsync()];
        }

        InitializeCurrentDateAndTimeline();
    }

    private void ThemeService_ThemeChanged(object? sender, EventArgs e)
    {
        CalendarCanvas.Invalidate();
        TimelineCanvas.Invalidate();
        RenderTimelineCards();
    }

    private void InitializeCurrentDateAndTimeline()
    {
        DateTimeOffset now = DateTimeOffset.Now;
        DateTimeOffset today = now.Date;
        CalendarEvent? nextEvent = GetNextUnpassedEvent(now);

        _focusedEventId = nextEvent?.Id;
        SelectDate(today, updateDisplayMonth: true, nextEvent?.Start);
    }

    private async void TodayButton_Click(object sender, RoutedEventArgs e)
    {
        await _commands.ExecuteAsync(AppCommandIds.GoToToday, sender);
    }

    private async void PreviousMonthButton_Click(object sender, RoutedEventArgs e)
    {
        await _commands.ExecuteAsync(AppCommandIds.PreviousMonth, sender);
    }

    private async void NextMonthButton_Click(object sender, RoutedEventArgs e)
    {
        await _commands.ExecuteAsync(AppCommandIds.NextMonth, sender);
    }

    private async void AddEventButton_Click(object sender, RoutedEventArgs e)
    {
        await _commands.ExecuteAsync(AppCommandIds.NewEvent, sender);
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

    private void RegisterCommandHandlers()
    {
        if (_commandRegistrations.Count > 0)
        {
            return;
        }

        _commandRegistrations.Add(_commands.RegisterHandler(AppCommandIds.GoToToday, GoToTodayAsync));
        _commandRegistrations.Add(_commands.RegisterHandler(AppCommandIds.PreviousMonth, PreviousMonthAsync));
        _commandRegistrations.Add(_commands.RegisterHandler(AppCommandIds.NextMonth, NextMonthAsync));
        _commandRegistrations.Add(_commands.RegisterHandler(AppCommandIds.NewEvent, NewEventAsync));
    }

    private Task GoToTodayAsync(AppCommandContext context)
    {
        SelectDate(DateTimeOffset.Now.Date, updateDisplayMonth: true);
        return Task.CompletedTask;
    }

    private Task PreviousMonthAsync(AppCommandContext context)
    {
        MoveDisplayMonth(-1);
        return Task.CompletedTask;
    }

    private Task NextMonthAsync(AppCommandContext context)
    {
        MoveDisplayMonth(1);
        return Task.CompletedTask;
    }

    private async Task NewEventAsync(AppCommandContext context)
    {
        if (_isEventEditorOpen)
        {
            return;
        }

        try
        {
            _isEventEditorOpen = true;
            await ShowEventEditorAsync(existingEvent: null);
        }
        finally
        {
            _isEventEditorOpen = false;
        }
    }

    private void MoveDisplayMonth(int monthOffset)
    {
        _displayMonth = _displayMonth.AddMonths(monthOffset);
        SelectDate(_displayMonth, updateDisplayMonth: false);
    }

    private void CalendarCanvas_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        Point point = e.GetCurrentPoint(CalendarCanvas).Position;
        DateTimeOffset? date = _calendarRenderer.HitTest(point);

        if (date is not null)
        {
            CalendarEvent? firstEvent = GetFirstEventOnDate(date.Value);
            _focusedEventId = firstEvent?.Id;
            SelectDate(date.Value, updateDisplayMonth: false, firstEvent?.Start);
            e.Handled = true;
        }
    }

    private void SelectDate(DateTimeOffset date, bool updateDisplayMonth, DateTimeOffset? timelinePosition = null)
    {
        _selectedDate = date.Date;
        _timelineCursor = timelinePosition ?? GetDefaultTimelinePosition(date);

        if (updateDisplayMonth)
        {
            _displayMonth = GetMonthStart(date);
        }

        AnimateTimelineToCursor(_timelineCursor);

        UpdateMonthTitle();
        UpdateTimelineCards(_selectedDate);
        CalendarCanvas.Invalidate();
        TimelineCanvas.Invalidate();
        RenderTimelineCards();
    }

    private void UpdateMonthTitle()
    {
        MonthTitle.Text = _displayMonth.ToString("MMMM yyyy");
    }

    private void UpdateTimelineCards(DateTimeOffset date)
    {
        RenderTimelineCards();
    }

    private void CalendarCanvas_Draw(CanvasControl sender, CanvasDrawEventArgs args)
    {
        _calendarRenderer.Draw(sender, args, _displayMonth, _selectedDate, _events);
    }

    private void TimelineCanvas_Draw(CanvasControl sender, CanvasDrawEventArgs args)
    {
        _timelineRenderer.Draw(
            sender,
            args,
            _timelineRangeStart,
            _timelineRangeEnd,
            _events,
            _timelineCursor,
            _focusedEventId,
            0.5f);
    }

    private void TimelineCanvas_PointerWheelChanged(object sender, PointerRoutedEventArgs e)
    {
        int wheelDelta = e.GetCurrentPoint(TimelineCanvas).Properties.MouseWheelDelta;
        if (wheelDelta == 0)
        {
            return;
        }

        TimelineTarget? target = GetTimelineWheelTarget(wheelDelta < 0);
        if (target is not null)
        {
            SelectTimelineTarget(target);
        }

        e.Handled = true;
    }

    private void TimelinePane_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        RenderTimelineCards();
    }

    private void Page_Unloaded(object sender, RoutedEventArgs e)
    {
        DisposeCommandHandlers();
        StopTimelineAnimation();
        _timelineCardClickTimer.Stop();
        _timelineCardClickTimer.Tick -= TimelineCardClickTimer_Tick;
        _themeService.ThemeChanged -= ThemeService_ThemeChanged;
        TimelineCanvas.RemoveFromVisualTree();
        TimelineCanvas = null!;
        CalendarCanvas.RemoveFromVisualTree();
        CalendarCanvas = null!;
    }

    private void DisposeCommandHandlers()
    {
        foreach (IDisposable registration in _commandRegistrations)
        {
            registration.Dispose();
        }

        _commandRegistrations.Clear();
    }

    private static DateTimeOffset GetMonthStart(DateTimeOffset date)
    {
        return new DateTimeOffset(date.Year, date.Month, 1, 0, 0, 0, date.Offset);
    }

    private void SetTimelineRangeToCursor()
    {
        (_timelineRangeStart, _timelineRangeEnd) = GetTimelineRange(_timelineCursor);
    }

    private void AnimateTimelineToCursor(DateTimeOffset center)
    {
        (DateTimeOffset targetStart, DateTimeOffset targetEnd) = GetTimelineRange(center);

        if (targetStart == _timelineRangeStart && targetEnd == _timelineRangeEnd)
        {
            StopTimelineAnimation();
            return;
        }

        _timelineAnimationFromStart = _timelineRangeStart;
        _timelineAnimationFromEnd = _timelineRangeEnd;
        _timelineAnimationToStart = targetStart;
        _timelineAnimationToEnd = targetEnd;
        _timelineAnimationDuration = GetTimelineAnimationDuration(_timelineAnimationFromStart, targetStart);
        _timelineAnimationStartTime = null;
        StartTimelineAnimation();
    }

    private static (DateTimeOffset Start, DateTimeOffset End) GetTimelineRange(DateTimeOffset center)
    {
        DateTimeOffset start = center - TimeSpan.FromTicks(TimelineVisibleRange.Ticks / 2);
        return (start, start + TimelineVisibleRange);
    }

    private static DateTimeOffset GetDefaultTimelinePosition(DateTimeOffset date)
    {
        return date.Date.AddHours(12);
    }

    private void StartTimelineAnimation()
    {
        if (_isTimelineAnimationRunning)
        {
            return;
        }

        CompositionTarget.Rendering += CompositionTarget_Rendering;
        _isTimelineAnimationRunning = true;
    }

    private void StopTimelineAnimation()
    {
        if (!_isTimelineAnimationRunning)
        {
            return;
        }

        CompositionTarget.Rendering -= CompositionTarget_Rendering;
        _timelineAnimationStartTime = null;
        _isTimelineAnimationRunning = false;
    }

    private void CompositionTarget_Rendering(object? sender, object e)
    {
        if (e is not RenderingEventArgs renderingArgs)
        {
            return;
        }

        _timelineAnimationStartTime ??= renderingArgs.RenderingTime;

        double elapsedMilliseconds = (renderingArgs.RenderingTime - _timelineAnimationStartTime.Value).TotalMilliseconds;
        double progress = Math.Clamp(elapsedMilliseconds / _timelineAnimationDuration.TotalMilliseconds, 0, 1);

        _timelineRangeStart = InterpolateDate(_timelineAnimationFromStart, _timelineAnimationToStart, progress);
        _timelineRangeEnd = InterpolateDate(_timelineAnimationFromEnd, _timelineAnimationToEnd, progress);
        TimelineCanvas.Invalidate();
        RenderTimelineCards();

        if (progress >= 1)
        {
            StopTimelineAnimation();
            _timelineRangeStart = _timelineAnimationToStart;
            _timelineRangeEnd = _timelineAnimationToEnd;
            TimelineCanvas.Invalidate();
            RenderTimelineCards();
        }
    }

    private static TimeSpan GetTimelineAnimationDuration(DateTimeOffset fromStart, DateTimeOffset toStart)
    {
        double travelDays = Math.Abs((toStart - fromStart).TotalDays);
        double milliseconds = travelDays / TimelineTravelDaysPerSecond * 1000;
        return TimeSpan.FromMilliseconds(Math.Clamp(
            milliseconds,
            TimelineMinAnimationMilliseconds,
            TimelineMaxAnimationMilliseconds));
    }

    private static DateTimeOffset InterpolateDate(DateTimeOffset from, DateTimeOffset to, double progress)
    {
        return from + TimeSpan.FromTicks((long)((to - from).Ticks * progress));
    }

    private TimelineTarget? GetTimelineWheelTarget(bool moveForward)
    {
        DateTimeOffset searchEnd = moveForward
            ? _timelineCursor.AddDays(7)
            : _timelineCursor.AddDays(-7);

        if (moveForward)
        {
            TimelineTarget? nextEvent = BuildEventTimelineTargets()
                .FirstOrDefault(target => target.Position > _timelineCursor && target.Position <= searchEnd);

            return nextEvent ?? new TimelineTarget(GetDefaultTimelinePosition(_selectedDate.AddDays(7)), null);
        }

        TimelineTarget? previousEvent = BuildEventTimelineTargets()
            .LastOrDefault(target => target.Position < _timelineCursor && target.Position >= searchEnd);

        return previousEvent ?? new TimelineTarget(GetDefaultTimelinePosition(_selectedDate.AddDays(-7)), null);
    }

    private List<TimelineTarget> BuildEventTimelineTargets()
    {
        return _events
            .Select(calendarEvent => new TimelineTarget(calendarEvent.Start, calendarEvent.Id))
            .OrderBy(target => target.Position)
            .ToList();
    }

    private CalendarEvent? GetFirstEventOnDate(DateTimeOffset date)
    {
        DateTimeOffset selectedDate = date.Date;
        return _events
            .Where(calendarEvent => calendarEvent.Start.Date == selectedDate)
            .OrderBy(calendarEvent => calendarEvent.Start)
            .ThenBy(calendarEvent => calendarEvent.Title)
            .FirstOrDefault();
    }

    private CalendarEvent? GetNextUnpassedEvent(DateTimeOffset now)
    {
        return _events
            .Where(calendarEvent => calendarEvent.End >= now)
            .OrderBy(calendarEvent => calendarEvent.Start < now ? now : calendarEvent.Start)
            .ThenBy(calendarEvent => calendarEvent.Start)
            .ThenBy(calendarEvent => calendarEvent.Title)
            .FirstOrDefault();
    }

    private void SelectTimelineTarget(TimelineTarget target)
    {
        _focusedEventId = target.EventId;
        SelectDate(target.Position, updateDisplayMonth: true);
        _timelineCursor = target.Position;
    }

    private void RenderTimelineCards()
    {
        if (TimelineCardsCanvas is null)
        {
            return;
        }

        double paneWidth = TimelinePane.ActualWidth;
        double paneHeight = TimelinePane.ActualHeight;
        if (paneWidth <= 0 || paneHeight <= 0)
        {
            return;
        }

        List<CalendarEvent> visibleEvents = _events
            .Where(calendarEvent => calendarEvent.Start >= _timelineRangeStart && calendarEvent.Start < _timelineRangeEnd)
            .OrderBy(calendarEvent => calendarEvent.Start)
            .ThenBy(calendarEvent => calendarEvent.Title)
            .ToList();

        if (visibleEvents.Count == 0)
        {
            RemoveTimelineCardsExcept(new HashSet<string>());
            AddEmptyTimelineCard(paneWidth, paneHeight);
            return;
        }

        RemoveEmptyTimelineCard();
        RemoveTimelineCardsExcept(visibleEvents.Select(calendarEvent => calendarEvent.Id).ToHashSet());

        double railX = paneWidth * 0.5;
        double cardWidth = Math.Max(128, Math.Min(176, (paneWidth - 48) / 2));
        double leftX = Math.Max(TimelinePanePadding, railX - cardWidth - 26);
        double rightX = Math.Min(paneWidth - cardWidth - TimelinePanePadding, railX + 26);
        Dictionary<string, int> eventOrder = GetStableEventOrder();
        List<double> cardTops = visibleEvents
            .Select(calendarEvent => MapDateToTimelinePaneY(calendarEvent.Start, paneHeight) - TimelineCardHeight / 2)
            .ToList();
        List<bool> cardSides = visibleEvents
            .Select(calendarEvent => IsTimelineCardOnLeft(calendarEvent, eventOrder))
            .ToList();

        int focusedIndex = visibleEvents.FindIndex(calendarEvent => calendarEvent.Id == _focusedEventId);
        AdjustTimelineCardLane(cardTops, cardSides, placeLeft: true, focusedIndex);
        AdjustTimelineCardLane(cardTops, cardSides, placeLeft: false, focusedIndex);

        for (int index = 0; index < visibleEvents.Count; index++)
        {
            double top = cardTops[index];
            if (top + TimelineCardHeight < 0 || top > paneHeight)
            {
                continue;
            }

            CalendarEvent calendarEvent = visibleEvents[index];
            bool isSelected = calendarEvent.Id == _focusedEventId;
            bool placeLeft = cardSides[index];
            UpdateTimelineEventCard(calendarEvent, placeLeft ? leftX : rightX, top, cardWidth, isSelected);
        }
    }

    private Dictionary<string, int> GetStableEventOrder()
    {
        return _events
            .OrderBy(calendarEvent => calendarEvent.Start)
            .ThenBy(calendarEvent => calendarEvent.Title)
            .Select((calendarEvent, index) => new { calendarEvent.Id, Index = index })
            .ToDictionary(calendarEvent => calendarEvent.Id, calendarEvent => calendarEvent.Index);
    }

    private static bool IsTimelineCardOnLeft(CalendarEvent calendarEvent, IReadOnlyDictionary<string, int> eventOrder)
    {
        return eventOrder.TryGetValue(calendarEvent.Id, out int index) && index % 2 == 0;
    }

    private static void AdjustTimelineCardLane(
        List<double> cardTops,
        IReadOnlyList<bool> cardSides,
        bool placeLeft,
        int focusedIndex)
    {
        List<int> laneIndices = Enumerable.Range(0, cardTops.Count)
            .Where(index => cardSides[index] == placeLeft)
            .ToList();

        if (laneIndices.Count < 2)
        {
            return;
        }

        int anchor = laneIndices.IndexOf(focusedIndex);
        if (anchor >= 0)
        {
            for (int index = anchor + 1; index < laneIndices.Count; index++)
            {
                int previous = laneIndices[index - 1];
                int current = laneIndices[index];
                cardTops[current] = Math.Max(cardTops[current], cardTops[previous] + TimelineCardHeight + TimelineCardGap);
            }

            for (int index = anchor - 1; index >= 0; index--)
            {
                int next = laneIndices[index + 1];
                int current = laneIndices[index];
                cardTops[current] = Math.Min(cardTops[current], cardTops[next] - TimelineCardHeight - TimelineCardGap);
            }

            return;
        }

        for (int index = 1; index < laneIndices.Count; index++)
        {
            int previous = laneIndices[index - 1];
            int current = laneIndices[index];
            cardTops[current] = Math.Max(cardTops[current], cardTops[previous] + TimelineCardHeight + TimelineCardGap);
        }
    }

    private double MapDateToTimelinePaneY(DateTimeOffset date, double paneHeight)
    {
        const double topPadding = 44;
        const double bottomPadding = 44;

        double usableHeight = Math.Max(1, paneHeight - topPadding - bottomPadding);
        double totalSeconds = Math.Max(1, (_timelineRangeEnd - _timelineRangeStart).TotalSeconds);
        double elapsedSeconds = Math.Clamp((date - _timelineRangeStart).TotalSeconds, 0, totalSeconds);
        return topPadding + (elapsedSeconds / totalSeconds) * usableHeight;
    }

    private void AddEmptyTimelineCard(double paneWidth, double paneHeight)
    {
        double railX = paneWidth * 0.5;
        double cardWidth = Math.Max(128, Math.Min(176, (paneWidth - 48) / 2));
        double left = Math.Min(paneWidth - cardWidth - TimelinePanePadding, railX + 26);

        if (_emptyTimelineCard is null)
        {
            _emptyTimelineCard = CreateTimelineCardShell(cardWidth, isSelected: true);
            _emptyTimelineCard.Child = new StackPanel
            {
                Spacing = 4,
                Children =
                {
                    new TextBlock
                    {
                        Text = _selectedDate.ToString("MMM d"),
                        FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
                        Foreground = ThemeService.GetBrush("MoongateTextBrush", Color.FromArgb(255, 74, 64, 58))
                    },
                    new TextBlock
                    {
                        Text = "No events",
                        Foreground = ThemeService.GetBrush("MoongateMutedTextBrush", Color.FromArgb(255, 138, 125, 111))
                    }
                }
            };
            TimelineCardsCanvas.Children.Add(_emptyTimelineCard);
        }

        UpdateTimelineCardShell(_emptyTimelineCard, cardWidth, isSelected: true);
        if (_emptyTimelineCard.Child is StackPanel { Children.Count: > 0 } stackPanel &&
            stackPanel.Children[0] is TextBlock dateText)
        {
            dateText.Text = _selectedDate.ToString("MMM d");
        }

        Canvas.SetLeft(_emptyTimelineCard, left);
        Canvas.SetTop(_emptyTimelineCard, MapDateToTimelinePaneY(_timelineCursor, paneHeight) - TimelineCardHeight / 2);
    }

    private void RemoveEmptyTimelineCard()
    {
        if (_emptyTimelineCard is null)
        {
            return;
        }

        TimelineCardsCanvas.Children.Remove(_emptyTimelineCard);
        _emptyTimelineCard = null;
    }

    private void RemoveTimelineCardsExcept(IReadOnlySet<string> visibleEventIds)
    {
        foreach (string eventId in _timelineCardViews.Keys.Where(eventId => !visibleEventIds.Contains(eventId)).ToList())
        {
            TimelineCardsCanvas.Children.Remove(_timelineCardViews[eventId].Card);
            _timelineCardViews.Remove(eventId);
        }
    }

    private void UpdateTimelineEventCard(CalendarEvent calendarEvent, double left, double top, double width, bool isSelected)
    {
        TimelineCardView view = GetOrCreateTimelineCardView(calendarEvent);
        UpdateTimelineCardShell(view.Card, width, isSelected);
        UpdateTimelineCardContent(view, calendarEvent);

        Canvas.SetLeft(view.Card, left);
        Canvas.SetTop(view.Card, top);
    }

    private TimelineCardView GetOrCreateTimelineCardView(CalendarEvent calendarEvent)
    {
        if (_timelineCardViews.TryGetValue(calendarEvent.Id, out TimelineCardView? existingView))
        {
            return existingView;
        }

        string eventId = calendarEvent.Id;
        Border card = CreateTimelineCardShell(width: 128, isSelected: false);
        card.IsDoubleTapEnabled = true;
        card.DoubleTapped += async (_, args) =>
        {
            args.Handled = true;
            CancelPendingTimelineCardSelection();
            SelectTimelineEventCard(eventId);
            await EditTimelineEventAsync(eventId);
        };
        card.Tapped += (_, args) =>
        {
            args.Handled = true;
            ScheduleTimelineCardSelection(eventId);
        };

        TextBlock timeText = new()
        {
            FontSize = 12,
            Foreground = ThemeService.GetBrush("MoongateMutedTextBrush", Color.FromArgb(255, 138, 125, 111))
        };

        TextBlock titleText = new()
        {
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
            TextTrimming = TextTrimming.CharacterEllipsis,
            Foreground = ThemeService.GetBrush("MoongateTextBrush", Color.FromArgb(255, 74, 64, 58))
        };

        TextBlock detailText = new()
        {
            FontSize = 12,
            TextTrimming = TextTrimming.CharacterEllipsis,
            Foreground = ThemeService.GetBrush("MoongateMutedTextBrush", Color.FromArgb(255, 138, 125, 111))
        };

        card.Child = new StackPanel
        {
            Spacing = 3,
            Children =
            {
                timeText,
                titleText,
                detailText
            }
        };

        TimelineCardView view = new(card, timeText, titleText, detailText);
        UpdateTimelineCardContent(view, calendarEvent);
        _timelineCardViews[eventId] = view;
        TimelineCardsCanvas.Children.Add(card);

        return view;
    }

    private static void UpdateTimelineCardContent(TimelineCardView view, CalendarEvent calendarEvent)
    {
        view.TimeText.Text = calendarEvent.TimeLabel;
        view.TitleText.Text = calendarEvent.Title;
        view.DetailText.Text = string.IsNullOrWhiteSpace(calendarEvent.Location)
            ? calendarEvent.Start.ToString("MMM d")
            : calendarEvent.Location;
    }

    private void ScheduleTimelineCardSelection(string eventId)
    {
        _pendingTimelineCardSelectionId = eventId;
        _timelineCardClickTimer.Stop();
        _timelineCardClickTimer.Start();
    }

    private void CancelPendingTimelineCardSelection()
    {
        _timelineCardClickTimer.Stop();
        _pendingTimelineCardSelectionId = null;
    }

    private void TimelineCardClickTimer_Tick(object? sender, object e)
    {
        _timelineCardClickTimer.Stop();

        if (_pendingTimelineCardSelectionId is not string eventId)
        {
            return;
        }

        _pendingTimelineCardSelectionId = null;
        SelectTimelineEventCard(eventId);
    }

    private void SelectTimelineEventCard(string eventId)
    {
        if (GetEventById(eventId) is not CalendarEvent eventToSelect)
        {
            return;
        }

        _focusedEventId = eventToSelect.Id;
        SelectDate(eventToSelect.Start, updateDisplayMonth: true);
    }

    private CalendarEvent? GetEventById(string eventId)
    {
        return _events.FirstOrDefault(candidate => candidate.Id == eventId);
    }

    private async Task EditTimelineEventAsync(string eventId)
    {
        if (_isEventEditorOpen)
        {
            return;
        }

        if (GetEventById(eventId) is not CalendarEvent eventToEdit)
        {
            return;
        }

        try
        {
            _isEventEditorOpen = true;
            AppLogger.Info($"Opening editor for timeline event '{eventToEdit.Id}'");
            await ShowEventEditorAsync(eventToEdit);
        }
        finally
        {
            _isEventEditorOpen = false;
        }
    }

    private static Border CreateTimelineCardShell(double width, bool isSelected)
    {
        Border card = new()
        {
            Width = width,
            Height = TimelineCardHeight,
            Padding = new Thickness(10, 8, 10, 8),
            CornerRadius = new CornerRadius(6),
            Background = ThemeService.GetBrush("MoongatePanelBackgroundBrush", Color.FromArgb(255, 250, 245, 235))
        };

        UpdateTimelineCardShell(card, width, isSelected);
        return card;
    }

    private static void UpdateTimelineCardShell(Border card, double width, bool isSelected)
    {
        card.Width = width;
        card.BorderBrush = ThemeService.GetBrush(isSelected ? "MoongateAccentLightBrush" : "MoongatePanelBorderBrush", Color.FromArgb(255, 212, 196, 168));
        card.BorderThickness = new Thickness(isSelected ? 2 : 1);
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

    private sealed record TimelineTarget(DateTimeOffset Position, string? EventId);

    private sealed record TimelineCardView(Border Card, TextBlock TimeText, TextBlock TitleText, TextBlock DetailText);

    private enum EventEditorAction
    {
        Upsert,
        Delete
    }
}
