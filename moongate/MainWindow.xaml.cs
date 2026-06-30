using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Input;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Moongate.Commands;
using Moongate.Services;
using Windows.System;
using Windows.UI.Core;
using Windows.UI;

// To learn more about WinUI, the WinUI project structure,
// and more about our project templates, see: http://aka.ms/winui-project-info.

namespace Moongate;

/// <summary>
/// The application window. This hosts a Frame that displays pages. Add your
/// UI and logic to MainPage.xaml / MainPage.xaml.cs instead of here so you
/// can use Page features such as navigation events and the Loaded lifecycle.
/// </summary>
public sealed partial class MainWindow : Window
{
    private readonly AppCommandRegistry _commands = AppServices.CommandRegistry;
    private readonly ThemeService _themeService = AppServices.ThemeService;

    public MainWindow()
    {
        AppLogger.Info("MainWindow constructor starting");
        InitializeComponent();
        AppLogger.Info("MainWindow XAML initialized");

        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);

        AppWindow.SetIcon("Assets/AppIcon.ico");
        ApplyCaptionButtonTheme();
        _themeService.ThemeChanged += ThemeService_ThemeChanged;

        RootFrame.Navigate(typeof(ShellPage));
        _commands.RegisterHandler(AppCommandIds.OpenSettings, OpenSettingsAsync);
        AppLogger.Info("RootFrame navigated to ShellPage");
    }

    private void ThemeService_ThemeChanged(object? sender, EventArgs e)
    {
        ApplyCaptionButtonTheme();
    }

    private async void RootLayout_PreviewKeyDown(object sender, KeyRoutedEventArgs args)
    {
        int keyCode = (int)args.Key;
        AppCommandModifiers modifiers = GetCurrentModifiers();

        if (ShouldIgnoreShortcut(args, keyCode, modifiers))
        {
            return;
        }

        args.Handled = await _commands.ExecuteShortcutAsync(keyCode, modifiers, args.OriginalSource);
    }

    private Task OpenSettingsAsync(AppCommandContext context)
    {
        if (RootFrame.Content is ShellPage shellPage)
        {
            shellPage.NavigateToSettings();
        }

        return Task.CompletedTask;
    }

    private bool ShouldIgnoreShortcut(
        KeyRoutedEventArgs args,
        int keyCode,
        AppCommandModifiers modifiers)
    {
        if (_commands.MatchesShortcut(AppCommandIds.OpenSettings, keyCode, modifiers))
        {
            return false;
        }

        return IsTextEditingTarget(args.OriginalSource as DependencyObject);
    }

    private static AppCommandModifiers GetCurrentModifiers()
    {
        AppCommandModifiers modifiers = AppCommandModifiers.None;

        if (IsKeyDown(VirtualKey.LeftControl) || IsKeyDown(VirtualKey.RightControl))
        {
            modifiers |= AppCommandModifiers.Control;
        }

        if (IsKeyDown(VirtualKey.LeftShift) || IsKeyDown(VirtualKey.RightShift))
        {
            modifiers |= AppCommandModifiers.Shift;
        }

        if (IsKeyDown(VirtualKey.LeftMenu) || IsKeyDown(VirtualKey.RightMenu))
        {
            modifiers |= AppCommandModifiers.Alt;
        }

        return modifiers;
    }

    private static bool IsKeyDown(VirtualKey key)
    {
        return InputKeyboardSource
            .GetKeyStateForCurrentThread(key)
            .HasFlag(CoreVirtualKeyStates.Down);
    }

    private static bool IsTextEditingTarget(DependencyObject? source)
    {
        DependencyObject? current = source;

        while (current is not null)
        {
            if (current is TextBox ||
                current is PasswordBox ||
                current is RichEditBox ||
                current is AutoSuggestBox ||
                current is ComboBox)
            {
                return true;
            }

            current = VisualTreeHelper.GetParent(current);
        }

        return false;
    }

    private void ApplyCaptionButtonTheme()
    {
        Color background = ThemeService.GetColor("MoongateAppBackgroundBrush", Color.FromArgb(255, 242, 234, 214));
        Color foreground = ThemeService.GetColor("MoongateNavigationIconBrush", Color.FromArgb(255, 74, 64, 58));
        Color hoverBackground = ThemeService.GetColor("MoongateNavigationHoverBackgroundBrush", Color.FromArgb(255, 255, 231, 170));
        Color hoverForeground = ThemeService.GetColor("MoongateNavigationHoverIconBrush", Color.FromArgb(255, 248, 203, 92));
        Color pressedBackground = ThemeService.GetColor("MoongateNavigationHoverBackgroundBrush", Color.FromArgb(255, 255, 231, 170));
        Color inactiveForeground = ThemeService.GetColor("MoongateMutedTextBrush", Color.FromArgb(255, 138, 125, 111));

        AppWindow.TitleBar.ButtonBackgroundColor = background;
        AppWindow.TitleBar.ButtonForegroundColor = foreground;
        AppWindow.TitleBar.ButtonHoverBackgroundColor = hoverBackground;
        AppWindow.TitleBar.ButtonHoverForegroundColor = hoverForeground;
        AppWindow.TitleBar.ButtonPressedBackgroundColor = pressedBackground;
        AppWindow.TitleBar.ButtonPressedForegroundColor = foreground;
        AppWindow.TitleBar.ButtonInactiveBackgroundColor = background;
        AppWindow.TitleBar.ButtonInactiveForegroundColor = inactiveForeground;
    }
}
