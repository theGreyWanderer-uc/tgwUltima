//theurgyRestoration.uc

void theurgyRestoration object#() () {
    UI_error_message("theurgyRestoration executing");

    var party = [AVATAR] & UI_get_party_list();
    var needs_restoration = false;

    for (member in party) {
        if (member->get_npc_prop(HEALTH) < member->get_npc_prop(STRENGTH)
            || UI_get_item_flag(member, POISONED)
            || UI_get_item_flag(member, PARALYZED)
            || UI_get_item_flag(member, ASLEEP)) {
            needs_restoration = true;
        }
    }

    if (!needs_restoration) {
        item_say("@We are already in perfect health!@");
        UI_error_message("Party does not need restoration - return");
        return;
    }

    if (!spendMagicMana(item, 15)) {
        return;
    }
    
    UI_error_message("Begin Animation and Effects");
    item_say("@Vas In Mani@");
    
    script item {
        nohalt;
        actor frame reach_1h;
        actor frame raise_1h;
        actor frame strike_1h;
        sfx 64;
    }

    for (member in party) {
        member->halt_scheduled();
        restoreNpcToFullHealth(member);
        cureBasicNpcStatuses(member);
    }

    UI_error_message("End Animation and Effects");
}
