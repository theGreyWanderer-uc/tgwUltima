using System;

namespace Moongate.Commands;

[Flags]
public enum AppCommandModifiers
{
    None = 0,
    Control = 1,
    Shift = 2,
    Alt = 4
}
