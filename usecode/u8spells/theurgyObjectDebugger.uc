//debug flags tool
static var wtf;

void theurgyObjectDebugger object#() () {
    var caster = AVATAR;

    // Array of known flag names for flags 0 to 38
    var flag_names = [
        "INVISIBLE", "ASLEEP", "CHARMED", "CURSED", "DEAD", "", "IN_PARTY", 
        "PARALYZED", "POISONED", "PROTECTION", "ON_MOVING_BARGE", "OKAY_TO_TAKE", 
        "MIGHT", "IMMUNITIES", "CANT_DIE", "IN_ACTION", "DONT_MOVE", "", 
        "TEMPORARY", "", "ACTIVE_SAILOR", "OKAY_TO_LAND", "SI_DONT_RENDER", 
        "IN_DUNGEON", "IS_SOLID", "CONFUSED", "ACTIVE_BARGE", "", "MET", 
        "SI_TOURNAMENT", "SI_ZOMBIE", "NO_SPELL_CASTING", "POLYMORPH", 
        "TATTOOED", "READ", "ISPETRA", "CAN_FLY", "FREEZE", "NAKED"
    ];

    // Output header
    UI_error_message("Checking flags for Avatar:");

    // Check flags from 0 to 101
    var i;
    i = 0;
    while (i <= 101) {
        var name;
        if (i < 39) {
            name = flag_names[i + 1];
            if (name == "") {
                name = "FLAG_" + i;
            }
        } else {
            name = "FLAG_" + i;
        }

        // Output only if the flag is set
        if (UI_get_item_flag(caster, i)) {
            UI_error_message(name + " (FLAG " + i + ") is SET.");
        }

        i = i + 1;
    }
}


/*

//find nearby shapes tool
void theurgyObjectDebugger object#() () {


    // Debug item
    var item_shape = UI_get_item_shape(item);
    var item_npc = UI_get_npc_number(item);
    UI_error_message("Item - Shape: " + item_shape + ", NPC: " + item_npc);

    // Find all objects within 5 tiles of the caster (item), using SHAPE_ANY and a comprehensive mask
    var nearby = UI_find_nearby(item, -359, 50, 0xF0);

    // Print a header to the console
    UI_error_message("Debugging objects within 5 tiles of the caster:");

    // Check if any objects were found
    if (UI_get_array_size(nearby) == 0) {
        UI_error_message("No objects found.");
    } else {
        // Loop through all found objects and print their details
        var obj;
        for (obj in nearby) {
            var shape = UI_get_item_shape(obj);
            var pos = UI_get_object_position(obj);
            UI_error_message("Object shape: " + shape + " at (" + pos[1] + ", " + pos[2] + ", " + pos[3] + ")");
        }
    }

    // Print a footer to mark the end of the list
    UI_error_message("End of list.");
}*/