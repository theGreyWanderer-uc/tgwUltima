using System.Collections.ObjectModel;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Moongate.Models;
using Moongate.Services;

namespace Moongate;

public sealed partial class AgendaPage : Page
{
    private readonly ICalendarEventRepository _eventRepository = AppServices.EventRepository;

    public ObservableCollection<CalendarEvent> UpcomingEvents { get; } = [];

    public AgendaPage()
    {
        InitializeComponent();
        Loaded += AgendaPage_Loaded;
    }

    private async void AgendaPage_Loaded(object sender, RoutedEventArgs e)
    {
        DateTimeOffset start = DateTimeOffset.Now.Date;
        DateTimeOffset end = start.AddDays(30);
        IReadOnlyList<CalendarEvent> events = await _eventRepository.GetEventsInRangeAsync(start, end);

        UpcomingEvents.Clear();
        foreach (CalendarEvent calendarEvent in events)
        {
            UpcomingEvents.Add(calendarEvent);
        }

        EmptyText.Visibility = UpcomingEvents.Count == 0
            ? Visibility.Visible
            : Visibility.Collapsed;
    }
}
