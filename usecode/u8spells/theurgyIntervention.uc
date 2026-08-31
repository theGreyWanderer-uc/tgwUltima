//theurgyIntervention.uc

// mode 0 = read, mode 1 = write; single-slot, so only one active cast is supported.
var interventionEffectStore(var mode, var val) {
    static var stored;
    if (mode == 1) { stored = val; }
    return stored;
}

var interventionActiveStore(var mode, var val) {
    static var stored;
    if (mode == 1) { stored = val; }
    return stored;
}

var interventionOriginalHPStore(var mode, var val) {
    static var stored;
    if (mode == 1) { stored = val; }
    return stored;
}

// East+2, south+2, up+3 relative to caster.
var interventionOffsetPos(var pos) {
    return [pos[1] + 2, pos[2] + 2, pos[3] + 3];
}

void theurgyInterventionExpire object#() () {
    UI_error_message("theurgyInterventionExpire called");
    var caster = item;
    interventionActiveStore(1, false);

    // Defensive clear - Exult's Npc_protection_timer already decays PROTECTION independently.
    UI_clear_item_flag(caster, PROTECTION);

    var originalHP = interventionOriginalHPStore(0, 0);
    setNpcPropAbsolute(caster, HEALTH, originalHP);

    var effect = interventionEffectStore(0, 0);
    if (effect) {
        UI_remove_item(effect);
        UI_error_message("Intervention effect expired and removed");
    }
}

void theurgyInterventionFollow object#() () {
    if (!interventionActiveStore(0, 0)) {
        return;
    }

    var caster = item;
    var effect = interventionEffectStore(0, 0);

    if (!effect || !caster) {
        return;
    }

    var casterPos = UI_get_object_position(caster);
    if (casterPos && UI_get_array_size(casterPos) >= 3) {
        UI_move_object(effect, interventionOffsetPos(casterPos), false);
    }

    var currentHP = UI_get_npc_prop(caster, HEALTH);
    if (currentHP != 200) {
        setNpcPropAbsolute(caster, HEALTH, 200);
    }

    // nohalt required - a non-nohalt script on 'caster' would halt this pending reschedule.
    script caster after 1 ticks {
        nohalt;
        call theurgyInterventionFollow;
    }
}

void theurgyIntervention object#() () {
    UI_error_message("theurgyIntervention executing");

    var caster = item;
    if (!spendMagicMana(caster, 15)) {
        return;
    }

    UI_error_message("Begin Animation and Effects");
    item_say("@In Sanct An Jux@");

    script caster {
        nohalt;
        actor frame CAST_1;
        actor frame CAST_2;
        sfx 90; //SI Protection spell's sfx
        wait 4;
        actor frame STAND;
    }

    // Engine grants +3 defense and power immunity, and auto-decays after ~60-80s (actors.cc/npctime.cc).
    UI_set_item_flag(caster, PROTECTION);

    var originalHP = UI_get_npc_prop(caster, HEALTH);
    interventionOriginalHPStore(1, originalHP);
    setNpcPropAbsolute(caster, HEALTH, 200);

    var casterPos = UI_get_object_position(caster);
    if (!casterPos || UI_get_array_size(casterPos) < 3) {
        UI_error_message("Error: Failed to get caster position!");
        return;
    }

    var effect = UI_create_new_object(SHAPE_INTERVENTION_SPELL);
    if (!effect) {
        UI_error_message("Error: Intervention effect shape creation failed");
        return;
    }

    UI_update_last_created(interventionOffsetPos(casterPos));
    interventionEffectStore(1, effect);
    interventionActiveStore(1, true);

    // nohalt required - a non-nohalt script on 'caster' would halt this pending reschedule.
    script caster after 1 ticks {
        nohalt;
        call theurgyInterventionFollow;
    }

    var baseDuration = 60;
    var duration = randomSpellDuration(baseDuration, 30);  //30-90 seconds
    UI_error_message("Intervention effect duration: " + duration + " seconds");

    // nohalt required - would otherwise halt the pending follow-loop reschedule above.
    script caster after (duration * 10) ticks {
        nohalt;
        call theurgyInterventionExpire;
    }

    UI_error_message("Intervention effect shape now tracks caster position; caster has PROTECTION");
    UI_error_message("End Animation and Effects");
}