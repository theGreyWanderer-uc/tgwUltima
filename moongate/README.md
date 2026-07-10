# Moongate

Moongate is a Windows App SDK / WinUI 3 calendar app.

## Build

```powershell
dotnet build .\Moongate.sln -c Debug -p:Platform=x64
```

## Run

```powershell
dotnet run --project .\Moongate.csproj -c Debug -p:Platform=x64 --launch-profile "Moongate (Package)"
```

The project includes `Microsoft.Graphics.Win2D` from the start so future dense calendar surfaces can move to Win2D without changing the app's package/runtime shape later.

## App Shape

`ShellPage` hosts the main `NavigationView`. `MainPage` is the month calendar and integrated timeline rail surface, and `SettingsPage` owns app-level configuration such as themes and diagnostics.

## Commands

App actions are defined in `Commands\AppCommandRegistry` and exposed through `AppServices.CommandRegistry`. Pages register handlers while active, so buttons, keyboard shortcuts, and future menu/command-palette surfaces can all invoke the same command IDs.

Current shortcuts:

| Command | Shortcut |
| --- | --- |
| Open settings | `Ctrl+,` |
| New event | `Ctrl+N` |
| Go to today | `Ctrl+T` |
| Previous month | `Alt+Left` |
| Next month | `Alt+Right` |

## Event Storage

Events are accessed through `ICalendarEventRepository`. The current implementation is `JsonCalendarEventRepository`, which stores indented JSON in the app's local data folder as `events.json`. This keeps the first model easy to inspect and migrate; SQLite is the likely next backing store once recurrence, full-text search, account sync, and heavier range queries become central.

The event editor supports add, edit, delete, date/time selection, category colors, location, notes, and end-after-start validation.

## Rendering

The month grid is drawn by `MonthCalendarRenderer` on a Win2D `CanvasControl`. The main month surface is paired with a left-side timeline pane: a Win2D rail plus alternating XAML event cards in a rolling seven-day window centered on the selected date or event time. On startup, the calendar opens on today and the rail seeks to the next event whose end time has not passed. Calendar day clicks prefer the first event on that day when one exists, selected dots draw larger than normal markers, and rail scrolling moves by event targets inside the next/previous week when events exist, otherwise jumping by one week. Blank rail clicks do not move the timeline; wheel input is the rail navigation gesture for now. Event cards use the same date-to-vertical-position mapping as the rail indicators, then apply per-side spacing only where needed to stay readable. Single-clicking a rail event card selects and seeks to it; double-clicking does the same and opens the event editor. The main rail uses `CompositionTarget.Rendering` only while it is moving, so short animations are frame-synchronized without keeping a permanent animation loop alive. Event card controls are reused during animation and only their position/content/style is updated, reducing per-frame XAML allocation and layout work. XAML remains responsible for shell chrome, dialogs, settings, and event-card interaction.

## Themes

Themes are based on semantic WinUI resources such as `MoongateAppBackgroundBrush`, `MoongateTextBrush`, `MoongateAccentBrush`, and calendar-specific tokens. `ThemeService` updates those resources and stores the selected theme in local app settings. Win2D rendering reads the same resources through `CalendarRenderTheme`, so drawn calendar pixels and XAML controls stay on the same palette. Theme selection lives in Settings.

## Diagnostics

Debug builds write startup and unhandled-exception logs to the packaged app's local data folder:

```powershell
$pkg = Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory |
  Where-Object { $_.Name -like 'A3366B1A-CBCB-45BB-AE4B-6E74F53DF3E6*' } |
  Select-Object -First 1
Get-ChildItem (Join-Path $pkg.FullName 'LocalState\logs')
```

Release builds can opt into the same logging with `MOONGATE_DEBUG_LOG=1` or the local setting `moongate-debug-logging=true`.
