//theurgyHearTruth.uc

void theurgyHearTruth object#() () {
    UI_error_message("theurgyHearTruth executing");

    var caster = item;

    if (!spendMagicMana(caster, 3)) {
        return;
    }

    UI_error_message("Begin Animation and Effects");
    item_say("@An Quas Lor@");

    script caster {
        nohalt;
        actor frame CAST_1;
        actor frame CAST_2;
        sfx 67;
        wait 4;
        actor frame STAND;
    }

    script caster {
        nohalt;
        call spellSetGflag, HEAR_TRUTH_ACTIVE;
    }

    var duration = staticSpellDuration(300);
    UI_error_message("Hear Truth duration: " + duration + " seconds");

    script caster after (duration * 10) ticks {
        nohalt;
        call spellClearGflag, HEAR_TRUTH_ACTIVE;
    }

    UI_error_message("Hear Truth active");
    UI_error_message("End Animation and Effects");
}
