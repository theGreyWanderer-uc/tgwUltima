//theurgyFadeFromSight.uc

void theurgyFadeFromSight object#() () {
    UI_error_message("theurgyFadeFromSight executing");

    var caster = item;
    var curMana = caster->get_npc_prop(MANA);
    UI_error_message("curMana proc eval using -caster->get_npc_prop(MANA)- before checking:" + curMana);

    if (!spendMagicMana(caster, 5)) {
        return;
    }

    UI_error_message("Begin Animation and Effects");
    item_say("@Quas An Lor@");

    script caster {
        nohalt;
        sfx 67;
        actor frame cast_up;
        actor frame cast_out;
        actor frame strike_2h;
        call spellSetFlag, INVISIBLE; //spellSetFlag from u8eSpellFunctions.uc
    }

    UI_error_message("End Animation and Effects");
    UI_error_message("Caster should now be invisible");

    var baseDuration = 180;  //3 minutes in seconds
    var duration = randomSpellDuration(baseDuration, 30);  //total duration in seconds, 150-210

    UI_error_message("Invisibility duration: " + duration + " seconds");

     //schedule the end of the invisibility effect
    script caster after (duration * 10) ticks {
        nohalt;
        call spellClearFlag, INVISIBLE;  //remove the INVISIBLE flag - spellClearFlag from u8eSpellFunctions.uc
    }
}