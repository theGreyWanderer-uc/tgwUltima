Some limitations that I know of:
Usecode compiler doesn’t scan the entire file for function declarations before compiling; it processes strictly top-down. goto: is possible but strongly warned against usage and compiler will complain.
Usecode cannot implicitly pass variables via the callback context like: (caster as obj in UI_si_path_run_usecode), it seems stricter—variables don’t cross file boundaries without explicit global declaration or passing mechanisms.
You cannot use var declarations in any Usecode script blocks. SI’s script { ... } is a lightweight scheduler, no variable declarations allowed, only direct commands like move [x, y, z], wait n, or call function.
You cannot use var declarations in any for loop statements. Instead, you need to declare the variable outside the loop and then use it in the loop.
The compiler does not support the C-style for loop syntax. In Usecode, for loops are designed to iterate over arrays using the in keyword. The C-style for loop with initialization, condition, and increment is not valid.
Ternary-like conditional expressions are not supported in Usecode. Usecode is a strict scripting language with limitations similar to a simplified C, and it does not support the ternary operator (?:) or similar shorthand conditionals involved in complex concatenation in a single expression.
The syntax for array slicing (array[start : end]) is not supported in the Usecode.
Sometimes Usecode seems to enforce that the main entry function (like entryFunction object#() ()) must be the first function in the .uc file, with no definitions (functions or variables) preceding it. I'm not sure where/why this applies in some cases yet.
Usecode doesn't support the or operator for assigning default values in variable declarations. In cases like this we need to do an explicit conditional check to assign a value as such:
var available = frame_counts[frame];
if (!available) {
    available = 0;
}

