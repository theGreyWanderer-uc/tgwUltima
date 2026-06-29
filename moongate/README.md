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

`ShellPage` hosts the main `NavigationView`. `MainPage` is the month calendar and day-detail surface, `AgendaPage` shows the upcoming 30-day projection, and `SettingsPage` owns app-level configuration such as themes and diagnostics.

## Event Storage

Events are accessed through `ICalendarEventRepository`. The current implementation is `JsonCalendarEventRepository`, which stores indented JSON in the app's local data folder as `events.json`. This keeps the first model easy to inspect and migrate; SQLite is the likely next backing store once recurrence, full-text search, account sync, and heavier range queries become central.

The event editor supports add, edit, delete, date/time selection, category colors, location, notes, and end-after-start validation.

## Rendering

The month grid is drawn by `MonthCalendarRenderer` on a Win2D `CanvasControl`. XAML remains responsible for shell chrome, dialogs, settings, and day/agenda lists.

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
