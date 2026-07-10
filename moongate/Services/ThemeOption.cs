namespace Moongate.Services;

public sealed class ThemeOption
{
    public string Id { get; set; } = string.Empty;

    public string DisplayName { get; set; } = string.Empty;

    public IReadOnlyDictionary<string, Windows.UI.Color> Colors { get; set; } =
        new Dictionary<string, Windows.UI.Color>();
}
