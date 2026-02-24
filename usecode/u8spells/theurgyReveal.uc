//theurgyReveal.uc

void theurgyReveal object#() () {
    UI_error_message("theurgyReveal executing");

    var caster = getOuterContainer(item);
    var curMana = caster->get_npc_prop(MANA);
    UI_error_message("Mana before casting: " + curMana);

        if (curMana < 5) {
        item_say("@Not enough mana...@");
        UI_error_message("Not enough mana to cast spell - return");
        return;
    }

    //get caster's position and set search distance
    var findPos = UI_get_object_position(caster);
    var dist = 7;
    var revealables = [];

    //find nearby invisible objects
    var invisibles = findPos->find_nearby(SHAPE_ANY, dist, MASK_INVISIBLE);
    for (obj in invisibles) {
        if (obj->get_item_flag(INVISIBLE)) {
            revealables = revealables + [obj];
        }
    }

    caster->set_npc_prop(MANA, -5);
    UI_error_message("Begin Animation and Effects");
    item_say("@Ort Lor@");
    script item {
        actor frame LEAN;
        wait 4;
        actor frame KNEEL;
        sfx 67;
        wait 8;
        actor frame STAND;
    }
    UI_error_message("End Animation and Effects");

    //reveal objects
    if (revealables == []) {
        UI_error_message("No invisible objects found");
    } else {
        UI_error_message("Revealing objects: " + revealables);
        for (obj in revealables) {
            script obj after 5 ticks {
                nohalt;
                call spellClearFlag, INVISIBLE;
            }
            obj->obj_sprite_effect(ANIMATION_GREEN_BUBBLES, -1, -1, 0, 0, 0, -1);
        }
    }
}