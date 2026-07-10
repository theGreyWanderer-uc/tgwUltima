using Microsoft.UI.Xaml;
using Moongate.Services;

namespace Moongate;

/// <summary>
/// Provides application-specific behavior to supplement the default Application class.
/// </summary>
public partial class App : Application
{
    private Window? _window;

    /// <summary>
    /// Initializes the singleton application object. This is the first line of authored code
    /// executed, and as such is the logical equivalent of main() or WinMain().
    /// </summary>
    public App()
    {
        AppLogger.Initialize();
        AppLogger.Info("App constructor starting");

        UnhandledException += App_UnhandledException;
        AppDomain.CurrentDomain.UnhandledException += CurrentDomain_UnhandledException;
        TaskScheduler.UnobservedTaskException += TaskScheduler_UnobservedTaskException;

        try
        {
            InitializeComponent();
            AppLogger.Info("App XAML initialized");
        }
        catch (Exception exception)
        {
            AppLogger.Error(exception, "App InitializeComponent failed");
            throw;
        }
    }

    /// <summary>
    /// Invoked when the application is launched.
    /// </summary>
    /// <param name="args">Details about the launch request and process.</param>
    protected override void OnLaunched(Microsoft.UI.Xaml.LaunchActivatedEventArgs args)
    {
        AppLogger.Info("App launch starting");

        try
        {
            _window = new MainWindow();
            _window.Activate();
            AppLogger.Info("Main window activated");
        }
        catch (Exception exception)
        {
            AppLogger.Error(exception, "App launch failed");
            throw;
        }
    }

    private static void App_UnhandledException(object sender, Microsoft.UI.Xaml.UnhandledExceptionEventArgs e)
    {
        AppLogger.Error(e.Exception, "XAML unhandled exception");
    }

    private static void CurrentDomain_UnhandledException(object sender, System.UnhandledExceptionEventArgs e)
    {
        AppLogger.Error($"AppDomain unhandled exception{Environment.NewLine}{e.ExceptionObject}");
    }

    private static void TaskScheduler_UnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs e)
    {
        AppLogger.Error(e.Exception, "Unobserved task exception");
    }
}
