using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Windows.Storage;
using Windows.UI;

namespace Moongate.Services;

public sealed class ThemeService
{
    private const string ThemeSettingKey = "moongate-theme";
    private const string DefaultThemeId = "golden-hour";

    public static IReadOnlyList<ThemeOption> ThemeOptions { get; } =
    [
        CreateTheme(
            "golden-hour",
            "Golden Hour",
            ("MoongateAppBackgroundBrush", 0xFF, 0xF2, 0xEA, 0xD6),
            ("MoongatePanelBackgroundBrush", 0xFF, 0xFA, 0xF5, 0xEB),
            ("MoongatePanelBorderBrush", 0xFF, 0xD4, 0xC4, 0xA8),
            ("MoongateTextBrush", 0xFF, 0x4A, 0x40, 0x3A),
            ("MoongateMutedTextBrush", 0xFF, 0x8A, 0x7D, 0x6F),
            ("MoongateAccentBrush", 0xFF, 0xF4, 0xA9, 0x00),
            ("MoongateAccentLightBrush", 0xFF, 0xF8, 0xCB, 0x5C),
            ("MoongateActiveBrush", 0xFF, 0x6A, 0x9E, 0x4A),
            ("MoongateDangerBrush", 0xFF, 0xC1, 0x66, 0x6B),
            ("MoongateInverseTextBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarSurfaceBrush", 0xFF, 0xFA, 0xF5, 0xEB),
            ("MoongateCalendarHeaderBrush", 0xFF, 0xF5, 0xEF, 0xE0),
            ("MoongateCalendarOutOfMonthBrush", 0xFF, 0xF0, 0xE8, 0xD4),
            ("MoongateCalendarSelectedBrush", 0xFF, 0xFF, 0xE7, 0xAA),
            ("MoongateCalendarTodayBrush", 0xFF, 0xC1, 0x66, 0x6B),
            ("MoongateCalendarSundayBrush", 0xFF, 0x9E, 0x51, 0x47),
            ("MoongateCalendarEventBrush", 0xFF, 0x6A, 0x9E, 0x4A)),
        CreateTheme(
            "ocean-depths",
            "Ocean Depths",
            ("MoongateAppBackgroundBrush", 0xFF, 0xF1, 0xFA, 0xEE),
            ("MoongatePanelBackgroundBrush", 0xFF, 0xF9, 0xFC, 0xF7),
            ("MoongatePanelBorderBrush", 0xFF, 0xC4, 0xDB, 0xDA),
            ("MoongateTextBrush", 0xFF, 0x1A, 0x23, 0x32),
            ("MoongateMutedTextBrush", 0xFF, 0x4C, 0x5F, 0x70),
            ("MoongateAccentBrush", 0xFF, 0x2D, 0x8B, 0x8B),
            ("MoongateAccentLightBrush", 0xFF, 0xA8, 0xDA, 0xDC),
            ("MoongateActiveBrush", 0xFF, 0x2F, 0x9A, 0x77),
            ("MoongateDangerBrush", 0xFF, 0xC1, 0x66, 0x6B),
            ("MoongateInverseTextBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarSurfaceBrush", 0xFF, 0xF9, 0xFC, 0xF7),
            ("MoongateCalendarHeaderBrush", 0xFF, 0xE6, 0xF2, 0xEF),
            ("MoongateCalendarOutOfMonthBrush", 0xFF, 0xE1, 0xF1, 0xF0),
            ("MoongateCalendarSelectedBrush", 0xFF, 0xD2, 0xE9, 0xE8),
            ("MoongateCalendarTodayBrush", 0xFF, 0xC1, 0x66, 0x6B),
            ("MoongateCalendarSundayBrush", 0xFF, 0xB7, 0x47, 0x2A),
            ("MoongateCalendarEventBrush", 0xFF, 0x2D, 0x8B, 0x8B)),
        CreateTheme(
            "sunset-boulevard",
            "Sunset Boulevard",
            ("MoongateAppBackgroundBrush", 0xFF, 0xF8, 0xEF, 0xCF),
            ("MoongatePanelBackgroundBrush", 0xFF, 0xFF, 0xF7, 0xE0),
            ("MoongatePanelBorderBrush", 0xFF, 0xE3, 0xCF, 0x9E),
            ("MoongateTextBrush", 0xFF, 0x26, 0x46, 0x53),
            ("MoongateMutedTextBrush", 0xFF, 0x6C, 0x67, 0x56),
            ("MoongateAccentBrush", 0xFF, 0xE7, 0x6F, 0x51),
            ("MoongateAccentLightBrush", 0xFF, 0xF4, 0xA2, 0x61),
            ("MoongateActiveBrush", 0xFF, 0x4A, 0x8D, 0x6D),
            ("MoongateDangerBrush", 0xFF, 0xB7, 0x47, 0x2A),
            ("MoongateInverseTextBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarSurfaceBrush", 0xFF, 0xFF, 0xF7, 0xE0),
            ("MoongateCalendarHeaderBrush", 0xFF, 0xF6, 0xE5, 0xB8),
            ("MoongateCalendarOutOfMonthBrush", 0xFF, 0xF7, 0xE7, 0xBD),
            ("MoongateCalendarSelectedBrush", 0xFF, 0xF2, 0xD9, 0xA4),
            ("MoongateCalendarTodayBrush", 0xFF, 0xB7, 0x47, 0x2A),
            ("MoongateCalendarSundayBrush", 0xFF, 0xB7, 0x47, 0x2A),
            ("MoongateCalendarEventBrush", 0xFF, 0xE7, 0x6F, 0x51)),
        CreateTheme(
            "forest-canopy",
            "Forest Canopy",
            ("MoongateAppBackgroundBrush", 0xFF, 0xFA, 0xF9, 0xF6),
            ("MoongatePanelBackgroundBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongatePanelBorderBrush", 0xFF, 0xD7, 0xDC, 0xC8),
            ("MoongateTextBrush", 0xFF, 0x2D, 0x4A, 0x2B),
            ("MoongateMutedTextBrush", 0xFF, 0x6F, 0x78, 0x65),
            ("MoongateAccentBrush", 0xFF, 0x7D, 0x84, 0x71),
            ("MoongateAccentLightBrush", 0xFF, 0xA4, 0xAC, 0x86),
            ("MoongateActiveBrush", 0xFF, 0x4F, 0x8A, 0x63),
            ("MoongateDangerBrush", 0xFF, 0xA8, 0x68, 0x63),
            ("MoongateInverseTextBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarSurfaceBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarHeaderBrush", 0xFF, 0xEF, 0xF1, 0xE8),
            ("MoongateCalendarOutOfMonthBrush", 0xFF, 0xED, 0xF1, 0xE4),
            ("MoongateCalendarSelectedBrush", 0xFF, 0xDF, 0xE7, 0xCE),
            ("MoongateCalendarTodayBrush", 0xFF, 0xA8, 0x68, 0x63),
            ("MoongateCalendarSundayBrush", 0xFF, 0xA8, 0x68, 0x63),
            ("MoongateCalendarEventBrush", 0xFF, 0x7D, 0x84, 0x71)),
        CreateTheme(
            "modern-minimalist",
            "Modern Minimalist",
            ("MoongateAppBackgroundBrush", 0xFF, 0xF0, 0xF2, 0xF4),
            ("MoongatePanelBackgroundBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongatePanelBorderBrush", 0xFF, 0xD3, 0xD3, 0xD3),
            ("MoongateTextBrush", 0xFF, 0x2A, 0x31, 0x38),
            ("MoongateMutedTextBrush", 0xFF, 0x68, 0x76, 0x82),
            ("MoongateAccentBrush", 0xFF, 0x70, 0x80, 0x90),
            ("MoongateAccentLightBrush", 0xFF, 0x98, 0xA8, 0xB8),
            ("MoongateActiveBrush", 0xFF, 0x3D, 0x8F, 0x6B),
            ("MoongateDangerBrush", 0xFF, 0xB3, 0x53, 0x5F),
            ("MoongateInverseTextBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarSurfaceBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarHeaderBrush", 0xFF, 0xEB, 0xEF, 0xF2),
            ("MoongateCalendarOutOfMonthBrush", 0xFF, 0xEE, 0xF2, 0xF5),
            ("MoongateCalendarSelectedBrush", 0xFF, 0xE2, 0xE8, 0xEE),
            ("MoongateCalendarTodayBrush", 0xFF, 0xB3, 0x53, 0x5F),
            ("MoongateCalendarSundayBrush", 0xFF, 0xB3, 0x53, 0x5F),
            ("MoongateCalendarEventBrush", 0xFF, 0x70, 0x80, 0x90)),
        CreateTheme(
            "arctic-frost",
            "Arctic Frost",
            ("MoongateAppBackgroundBrush", 0xFF, 0xFA, 0xFA, 0xFA),
            ("MoongatePanelBackgroundBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongatePanelBorderBrush", 0xFF, 0xD8, 0xE2, 0xEE),
            ("MoongateTextBrush", 0xFF, 0x2A, 0x3C, 0x56),
            ("MoongateMutedTextBrush", 0xFF, 0x6A, 0x7F, 0x96),
            ("MoongateAccentBrush", 0xFF, 0x4A, 0x6F, 0xA5),
            ("MoongateAccentLightBrush", 0xFF, 0xD4, 0xE4, 0xF7),
            ("MoongateActiveBrush", 0xFF, 0x4F, 0x8C, 0xA3),
            ("MoongateDangerBrush", 0xFF, 0xAD, 0x6B, 0x74),
            ("MoongateInverseTextBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarSurfaceBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarHeaderBrush", 0xFF, 0xEE, 0xF4, 0xFB),
            ("MoongateCalendarOutOfMonthBrush", 0xFF, 0xED, 0xF3, 0xFB),
            ("MoongateCalendarSelectedBrush", 0xFF, 0xDD, 0xE9, 0xF8),
            ("MoongateCalendarTodayBrush", 0xFF, 0xAD, 0x6B, 0x74),
            ("MoongateCalendarSundayBrush", 0xFF, 0xAD, 0x6B, 0x74),
            ("MoongateCalendarEventBrush", 0xFF, 0x4A, 0x6F, 0xA5)),
        CreateTheme(
            "desert-rose",
            "Desert Rose",
            ("MoongateAppBackgroundBrush", 0xFF, 0xE8, 0xD5, 0xC4),
            ("MoongatePanelBackgroundBrush", 0xFF, 0xF5, 0xEB, 0xE3),
            ("MoongatePanelBorderBrush", 0xFF, 0xD9, 0xBF, 0xAE),
            ("MoongateTextBrush", 0xFF, 0x4C, 0x30, 0x40),
            ("MoongateMutedTextBrush", 0xFF, 0x8A, 0x6B, 0x6F),
            ("MoongateAccentBrush", 0xFF, 0xB8, 0x7D, 0x6D),
            ("MoongateAccentLightBrush", 0xFF, 0xD4, 0xA5, 0xA5),
            ("MoongateActiveBrush", 0xFF, 0xA7, 0x73, 0x68),
            ("MoongateDangerBrush", 0xFF, 0x8F, 0x4A, 0x62),
            ("MoongateInverseTextBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarSurfaceBrush", 0xFF, 0xF5, 0xEB, 0xE3),
            ("MoongateCalendarHeaderBrush", 0xFF, 0xEF, 0xDC, 0xCF),
            ("MoongateCalendarOutOfMonthBrush", 0xFF, 0xF2, 0xE3, 0xD8),
            ("MoongateCalendarSelectedBrush", 0xFF, 0xEB, 0xD1, 0xC2),
            ("MoongateCalendarTodayBrush", 0xFF, 0x8F, 0x4A, 0x62),
            ("MoongateCalendarSundayBrush", 0xFF, 0x8F, 0x4A, 0x62),
            ("MoongateCalendarEventBrush", 0xFF, 0xB8, 0x7D, 0x6D)),
        CreateTheme(
            "tech-innovation",
            "Tech Innovation",
            ("MoongateAppBackgroundBrush", 0xFF, 0x10, 0x14, 0x18),
            ("MoongatePanelBackgroundBrush", 0xFF, 0x1E, 0x1E, 0x1E),
            ("MoongatePanelBorderBrush", 0xFF, 0x2F, 0x3A, 0x46),
            ("MoongateTextBrush", 0xFF, 0xF2, 0xF6, 0xFF),
            ("MoongateMutedTextBrush", 0xFF, 0xB9, 0xC4, 0xD4),
            ("MoongateAccentBrush", 0xFF, 0x00, 0x66, 0xFF),
            ("MoongateAccentLightBrush", 0xFF, 0x00, 0xFF, 0xFF),
            ("MoongateActiveBrush", 0xFF, 0x00, 0xD6, 0xB8),
            ("MoongateDangerBrush", 0xFF, 0xFF, 0x5C, 0x7A),
            ("MoongateInverseTextBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarSurfaceBrush", 0xFF, 0x1E, 0x1E, 0x1E),
            ("MoongateCalendarHeaderBrush", 0xFF, 0x17, 0x1B, 0x1F),
            ("MoongateCalendarOutOfMonthBrush", 0xFF, 0x1A, 0x22, 0x30),
            ("MoongateCalendarSelectedBrush", 0xFF, 0x1D, 0x2C, 0x45),
            ("MoongateCalendarTodayBrush", 0xFF, 0xFF, 0x5C, 0x7A),
            ("MoongateCalendarSundayBrush", 0xFF, 0xFF, 0x5C, 0x7A),
            ("MoongateCalendarEventBrush", 0xFF, 0x00, 0x66, 0xFF)),
        CreateTheme(
            "botanical-garden",
            "Botanical Garden",
            ("MoongateAppBackgroundBrush", 0xFF, 0xF5, 0xF3, 0xED),
            ("MoongatePanelBackgroundBrush", 0xFF, 0xFC, 0xFA, 0xF4),
            ("MoongatePanelBorderBrush", 0xFF, 0xDD, 0xD4, 0xBF),
            ("MoongateTextBrush", 0xFF, 0x33, 0x4C, 0x3D),
            ("MoongateMutedTextBrush", 0xFF, 0x6F, 0x7A, 0x62),
            ("MoongateAccentBrush", 0xFF, 0xF9, 0xA6, 0x20),
            ("MoongateAccentLightBrush", 0xFF, 0xFB, 0xC7, 0x6E),
            ("MoongateActiveBrush", 0xFF, 0x4A, 0x7C, 0x59),
            ("MoongateDangerBrush", 0xFF, 0xB7, 0x47, 0x2A),
            ("MoongateInverseTextBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarSurfaceBrush", 0xFF, 0xFC, 0xFA, 0xF4),
            ("MoongateCalendarHeaderBrush", 0xFF, 0xEF, 0xE9, 0xDD),
            ("MoongateCalendarOutOfMonthBrush", 0xFF, 0xEF, 0xE8, 0xD6),
            ("MoongateCalendarSelectedBrush", 0xFF, 0xEC, 0xDC, 0xBF),
            ("MoongateCalendarTodayBrush", 0xFF, 0xB7, 0x47, 0x2A),
            ("MoongateCalendarSundayBrush", 0xFF, 0xB7, 0x47, 0x2A),
            ("MoongateCalendarEventBrush", 0xFF, 0xF9, 0xA6, 0x20)),
        CreateTheme(
            "midnight-galaxy",
            "Midnight Galaxy",
            ("MoongateAppBackgroundBrush", 0xFF, 0x1A, 0x12, 0x27),
            ("MoongatePanelBackgroundBrush", 0xFF, 0x25, 0x1A, 0x38),
            ("MoongatePanelBorderBrush", 0xFF, 0x3E, 0x35, 0x63),
            ("MoongateTextBrush", 0xFF, 0xE6, 0xE6, 0xFA),
            ("MoongateMutedTextBrush", 0xFF, 0xB5, 0xA8, 0xCD),
            ("MoongateAccentBrush", 0xFF, 0x4A, 0x4E, 0x8F),
            ("MoongateAccentLightBrush", 0xFF, 0xA4, 0x90, 0xC2),
            ("MoongateActiveBrush", 0xFF, 0x7C, 0xA9, 0xDD),
            ("MoongateDangerBrush", 0xFF, 0xCF, 0x6C, 0x9B),
            ("MoongateInverseTextBrush", 0xFF, 0xFF, 0xFF, 0xFF),
            ("MoongateCalendarSurfaceBrush", 0xFF, 0x25, 0x1A, 0x38),
            ("MoongateCalendarHeaderBrush", 0xFF, 0x22, 0x17, 0x33),
            ("MoongateCalendarOutOfMonthBrush", 0xFF, 0x2E, 0x24, 0x46),
            ("MoongateCalendarSelectedBrush", 0xFF, 0x38, 0x2C, 0x54),
            ("MoongateCalendarTodayBrush", 0xFF, 0xCF, 0x6C, 0x9B),
            ("MoongateCalendarSundayBrush", 0xFF, 0xA4, 0x90, 0xC2),
            ("MoongateCalendarEventBrush", 0xFF, 0x4A, 0x4E, 0x8F))
    ];

    public event EventHandler? ThemeChanged;

    public string CurrentThemeId { get; private set; } = DefaultThemeId;

    public void ApplyStoredTheme()
    {
        object? stored = ApplicationData.Current.LocalSettings.Values[ThemeSettingKey];
        string themeId = stored as string ?? DefaultThemeId;

        AppLogger.Info($"Applying stored theme '{themeId}'");
        ApplyTheme(themeId, persist: false);
    }

    public void ApplyTheme(string themeId, bool persist)
    {
        ThemeOption theme = ThemeOptions.FirstOrDefault(option => option.Id == themeId)
            ?? ThemeOptions.First(option => option.Id == DefaultThemeId);

        AppLogger.Info($"Applying theme '{theme.Id}'");

        foreach ((string key, Color color) in theme.Colors)
        {
            ApplyColorResource(key, color);
        }

        CurrentThemeId = theme.Id;

        if (persist)
        {
            ApplicationData.Current.LocalSettings.Values[ThemeSettingKey] = theme.Id;
        }

        ThemeChanged?.Invoke(this, EventArgs.Empty);
    }

    public static Color GetColor(string resourceKey, Color fallback)
    {
        if (Application.Current.Resources.TryGetValue(resourceKey, out object value))
        {
            return value switch
            {
                SolidColorBrush brush => brush.Color,
                Color color => color,
                _ => fallback
            };
        }

        return fallback;
    }

    public static SolidColorBrush GetBrush(string resourceKey, Color fallback)
    {
        if (Application.Current.Resources.TryGetValue(resourceKey, out object value) &&
            value is SolidColorBrush brush)
        {
            return brush;
        }

        return new SolidColorBrush(fallback);
    }

    private static ThemeOption CreateTheme(
        string id,
        string displayName,
        params (string Key, byte A, byte R, byte G, byte B)[] colors)
    {
        Dictionary<string, Color> colorMap = colors.ToDictionary(
            color => color.Key,
            color => Color.FromArgb(color.A, color.R, color.G, color.B));

        AddAliasColor(colorMap, "MoongateTextBrush", "MoongateCommandTextBrush");
        AddAliasColor(colorMap, "MoongateTextBrush", "MoongateCommandIconBrush");
        AddAliasColor(colorMap, "MoongateTextBrush", "MoongateNavigationTextBrush");
        AddAliasColor(colorMap, "MoongateTextBrush", "MoongateNavigationIconBrush");
        AddAliasColor(colorMap, "MoongateAccentLightBrush", "MoongateNavigationHoverTextBrush");
        AddAliasColor(colorMap, "MoongateAccentLightBrush", "MoongateNavigationHoverIconBrush");
        AddAliasColor(colorMap, "MoongateCalendarSelectedBrush", "MoongateNavigationHoverBackgroundBrush");
        AddAliasColor(colorMap, "MoongatePanelBackgroundBrush", "MoongateNavigationPaneBackgroundBrush");
        AddAliasColor(colorMap, "MoongatePanelBackgroundBrush", "MoongateInputBackgroundBrush");
        AddAliasColor(colorMap, "MoongateCalendarSelectedBrush", "MoongateInputHoverBackgroundBrush");
        AddAliasColor(colorMap, "MoongateTextBrush", "MoongateInputTextBrush");
        AddAliasColor(colorMap, "MoongateMutedTextBrush", "MoongateInputMutedTextBrush");
        AddAliasColor(colorMap, "MoongatePanelBorderBrush", "MoongateInputBorderBrush");
        AddAliasColor(colorMap, "MoongatePanelBackgroundBrush", "MoongateOverlayBackgroundBrush");
        AddAliasColor(colorMap, "MoongateCalendarSelectedBrush", "MoongateOverlayHoverBackgroundBrush");
        AddAliasColor(colorMap, "MoongateCalendarSelectedBrush", "MoongateOverlaySelectedBackgroundBrush");

        return new ThemeOption
        {
            Id = id,
            DisplayName = displayName,
            Colors = colorMap
        };
    }

    private static void AddAliasColor(Dictionary<string, Color> colorMap, string sourceKey, string aliasKey)
    {
        if (colorMap.ContainsKey(aliasKey))
        {
            return;
        }

        if (colorMap.TryGetValue(sourceKey, out Color color))
        {
            colorMap[aliasKey] = color;
        }
    }

    private static void ApplyColorResource(string key, Color color)
    {
        if (Application.Current.Resources.TryGetValue(key, out object value) &&
            value is SolidColorBrush brush)
        {
            brush.Color = color;
            return;
        }

        Application.Current.Resources[key] = new SolidColorBrush(color);
    }
}
