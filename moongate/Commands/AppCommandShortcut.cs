namespace Moongate.Commands;

public sealed record AppCommandShortcut(
    int KeyCode,
    AppCommandModifiers Modifiers,
    string DisplayText)
{
    public bool Matches(int keyCode, AppCommandModifiers modifiers)
    {
        return KeyCode == keyCode && Modifiers == modifiers;
    }
}
