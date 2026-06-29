using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Moongate.Services;

namespace Moongate;

public sealed partial class SettingsPage : Page
{
    private readonly ThemeService _themeService = AppServices.ThemeService;
    private bool _isLoading;

    public SettingsPage()
    {
        InitializeComponent();
        Loaded += SettingsPage_Loaded;
    }

    private void SettingsPage_Loaded(object sender, RoutedEventArgs e)
    {
        _isLoading = true;

        _themeService.ApplyStoredTheme();
        ThemeSelector.ItemsSource = ThemeService.ThemeOptions;
        ThemeSelector.DisplayMemberPath = nameof(ThemeOption.DisplayName);
        ThemeSelector.SelectedValuePath = nameof(ThemeOption.Id);
        ThemeSelector.SelectedValue = _themeService.CurrentThemeId;

        DebugLoggingSwitch.IsOn = AppLogger.IsEnabled;
        LogPathText.Text = $"Logs are written to {AppLogger.LogDirectory}";

        _isLoading = false;
    }

    private void ThemeSelector_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_isLoading)
        {
            return;
        }

        if (ThemeSelector.SelectedValue is string themeId &&
            themeId != _themeService.CurrentThemeId)
        {
            _themeService.ApplyTheme(themeId, persist: true);
        }
    }

    private void DebugLoggingSwitch_Toggled(object sender, RoutedEventArgs e)
    {
        if (_isLoading)
        {
            return;
        }

        AppLogger.SetDebugLoggingEnabled(DebugLoggingSwitch.IsOn);
        LogPathText.Text = $"Logs are written to {AppLogger.LogDirectory}";
    }
}
