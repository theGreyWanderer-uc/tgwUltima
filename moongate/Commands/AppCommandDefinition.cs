namespace Moongate.Commands;

public sealed record AppCommandDefinition(
    string Id,
    string Label,
    AppCommandScope Scope,
    AppCommandShortcut? DefaultShortcut);
