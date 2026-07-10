using System.Diagnostics;
using Windows.Storage;

namespace Moongate.Services;

public static class AppLogger
{
    private const string DebugLoggingSettingKey = "moongate-debug-logging";
    private static readonly object Lock = new();
    private static string? _logDirectory;
    private static bool _initialized;

    public static bool IsEnabled { get; private set; }

    public static string LogDirectory
    {
        get
        {
            EnsureInitialized();
            return _logDirectory!;
        }
    }

    public static void Initialize()
    {
        EnsureInitialized();
        Info("Logger initialized");
    }

    public static void Info(string message)
    {
        Write("INFO", message);
    }

    public static void Error(Exception exception, string message)
    {
        Write("ERROR", $"{message}{Environment.NewLine}{exception}");
    }

    public static void Error(string message)
    {
        Write("ERROR", message);
    }

    public static void SetDebugLoggingEnabled(bool isEnabled)
    {
        EnsureInitialized();

        try
        {
            ApplicationData.Current.LocalSettings.Values[DebugLoggingSettingKey] = isEnabled ? "true" : "false";
        }
        catch
        {
            // Logging configuration should never stop the app from running.
        }

        IsEnabled = IsDebugBuild() || isEnabled;
        Info($"Debug logging set to {IsEnabled}");
    }

    private static void Write(string level, string message)
    {
        EnsureInitialized();

        if (!IsEnabled)
        {
            return;
        }

        string line = $"{DateTimeOffset.Now:O} [{level}] {message}{Environment.NewLine}";

        lock (Lock)
        {
            File.AppendAllText(GetLogPath(), line);
        }

        Debug.WriteLine(line);
    }

    private static void EnsureInitialized()
    {
        if (_initialized)
        {
            return;
        }

        lock (Lock)
        {
            if (_initialized)
            {
                return;
            }

            _logDirectory = ResolveLogDirectory();
            Directory.CreateDirectory(_logDirectory);

            IsEnabled = IsDebugBuild() ||
                IsTruthy(Environment.GetEnvironmentVariable("MOONGATE_DEBUG_LOG")) ||
                IsTruthy(ReadLocalDebugLoggingSetting());

            _initialized = true;
        }
    }

    private static string GetLogPath()
    {
        return Path.Combine(LogDirectory, $"moongate-{DateTimeOffset.Now:yyyyMMdd}.log");
    }

    private static string ResolveLogDirectory()
    {
        try
        {
            return Path.Combine(ApplicationData.Current.LocalFolder.Path, "logs");
        }
        catch
        {
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            return Path.Combine(localAppData, "Moongate", "logs");
        }
    }

    private static string? ReadLocalDebugLoggingSetting()
    {
        try
        {
            return ApplicationData.Current.LocalSettings.Values[DebugLoggingSettingKey] as string;
        }
        catch
        {
            return null;
        }
    }

    private static bool IsTruthy(string? value)
    {
        return value is not null &&
            (value.Equals("1", StringComparison.OrdinalIgnoreCase) ||
             value.Equals("true", StringComparison.OrdinalIgnoreCase) ||
             value.Equals("yes", StringComparison.OrdinalIgnoreCase) ||
             value.Equals("on", StringComparison.OrdinalIgnoreCase));
    }

    private static bool IsDebugBuild()
    {
#if DEBUG
        return true;
#else
        return false;
#endif
    }
}
