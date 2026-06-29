using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Moongate.Services;

namespace Moongate;

public sealed partial class ShellPage : Page
{
    public ShellPage()
    {
        InitializeComponent();
        Loaded += ShellPage_Loaded;
    }

    private void ShellPage_Loaded(object sender, RoutedEventArgs e)
    {
        if (ContentFrame.Content is null)
        {
            NavigateTo("calendar");
            RootNavigation.SelectedItem = RootNavigation.MenuItems[0];
        }
    }

    private void RootNavigation_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItemContainer?.Tag is string tag)
        {
            NavigateTo(tag);
        }
    }

    private void NavigateTo(string tag)
    {
        Type pageType = tag switch
        {
            "agenda" => typeof(AgendaPage),
            "settings" => typeof(SettingsPage),
            _ => typeof(MainPage)
        };

        if (ContentFrame.CurrentSourcePageType != pageType)
        {
            AppLogger.Info($"Navigating shell to {pageType.Name}");
            ContentFrame.Navigate(pageType);
        }
    }
}
