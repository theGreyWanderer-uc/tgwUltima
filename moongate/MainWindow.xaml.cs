using Microsoft.UI.Xaml;
using Moongate.Services;
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
        AppLogger.Info("RootFrame navigated to ShellPage");
    }

    private void ThemeService_ThemeChanged(object? sender, EventArgs e)
    {
        ApplyCaptionButtonTheme();
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
