using Moongate.Services;
using Windows.System;

namespace Moongate.Commands;

public sealed class AppCommandRegistry
{
    private readonly Dictionary<string, AppCommandDefinition> _definitions;
    private readonly Dictionary<string, List<Func<AppCommandContext, Task>>> _handlers = [];
    private readonly object _lock = new();

    public AppCommandRegistry(IEnumerable<AppCommandDefinition> definitions)
    {
        _definitions = definitions.ToDictionary(definition => definition.Id);
    }

    public IReadOnlyCollection<AppCommandDefinition> Definitions => _definitions.Values;

    public static AppCommandRegistry CreateDefault()
    {
        return new AppCommandRegistry(
        [
            new(
                AppCommandIds.OpenSettings,
                "Open settings",
                AppCommandScope.Global,
                new AppCommandShortcut(188, AppCommandModifiers.Control, "Ctrl+,")),
            new(
                AppCommandIds.NewEvent,
                "New event",
                AppCommandScope.Calendar,
                new AppCommandShortcut((int)VirtualKey.N, AppCommandModifiers.Control, "Ctrl+N")),
            new(
                AppCommandIds.GoToToday,
                "Go to today",
                AppCommandScope.Calendar,
                new AppCommandShortcut((int)VirtualKey.T, AppCommandModifiers.Control, "Ctrl+T")),
            new(
                AppCommandIds.PreviousMonth,
                "Previous month",
                AppCommandScope.Calendar,
                new AppCommandShortcut((int)VirtualKey.Left, AppCommandModifiers.Alt, "Alt+Left")),
            new(
                AppCommandIds.NextMonth,
                "Next month",
                AppCommandScope.Calendar,
                new AppCommandShortcut((int)VirtualKey.Right, AppCommandModifiers.Alt, "Alt+Right"))
        ]);
    }

    public IDisposable RegisterHandler(
        string commandId,
        Func<AppCommandContext, Task> handler)
    {
        if (!_definitions.ContainsKey(commandId))
        {
            throw new ArgumentException($"Unknown command '{commandId}'.", nameof(commandId));
        }

        lock (_lock)
        {
            if (!_handlers.TryGetValue(commandId, out List<Func<AppCommandContext, Task>>? handlers))
            {
                handlers = [];
                _handlers[commandId] = handlers;
            }

            handlers.Add(handler);
        }

        return new CommandHandlerRegistration(this, commandId, handler);
    }

    public bool MatchesShortcut(
        string commandId,
        int keyCode,
        AppCommandModifiers modifiers)
    {
        return _definitions.TryGetValue(commandId, out AppCommandDefinition? definition) &&
            definition.DefaultShortcut?.Matches(keyCode, modifiers) == true;
    }

    public async Task<bool> ExecuteShortcutAsync(
        int keyCode,
        AppCommandModifiers modifiers,
        object? source = null)
    {
        foreach (AppCommandDefinition definition in _definitions.Values)
        {
            if (definition.DefaultShortcut?.Matches(keyCode, modifiers) == true &&
                await ExecuteAsync(definition.Id, source))
            {
                return true;
            }
        }

        return false;
    }

    public async Task<bool> ExecuteAsync(string commandId, object? source = null)
    {
        Func<AppCommandContext, Task>? handler = GetCurrentHandler(commandId);

        if (handler is null)
        {
            AppLogger.Info($"No active handler for command '{commandId}'");
            return false;
        }

        await handler(new AppCommandContext(source));
        return true;
    }

    private Func<AppCommandContext, Task>? GetCurrentHandler(string commandId)
    {
        lock (_lock)
        {
            return _handlers.TryGetValue(commandId, out List<Func<AppCommandContext, Task>>? handlers) &&
                handlers.Count > 0
                    ? handlers[^1]
                    : null;
        }
    }

    private void UnregisterHandler(
        string commandId,
        Func<AppCommandContext, Task> handler)
    {
        lock (_lock)
        {
            if (!_handlers.TryGetValue(commandId, out List<Func<AppCommandContext, Task>>? handlers))
            {
                return;
            }

            handlers.Remove(handler);

            if (handlers.Count == 0)
            {
                _handlers.Remove(commandId);
            }
        }
    }

    private sealed class CommandHandlerRegistration(
        AppCommandRegistry registry,
        string commandId,
        Func<AppCommandContext, Task> handler) : IDisposable
    {
        private bool _isDisposed;

        public void Dispose()
        {
            if (_isDisposed)
            {
                return;
            }

            registry.UnregisterHandler(commandId, handler);
            _isDisposed = true;
        }
    }
}
