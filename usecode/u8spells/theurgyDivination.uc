//theurgyDivination.uc

//declare getPaganCalendar utility/paganCalendar.uc
extern var getPaganCalendar();

//Theurgy Divination spell
void theurgyDivination object#() () {
    UI_error_message("theurgyDivination executing");

    //adjust this later
    var curMana = item->get_npc_prop(MANA);
    UI_error_message("curMana proc eval using -item->get_npc_prop(MANA)- before checking:" + curMana);

    if (curMana < 3) {
        item_say("@Not enough mana...@");
        UI_error_message("Not enough mana to cast spell - return");
        return;
    }

    //adjust this later
    item->set_npc_prop(MANA, -3);
    UI_error_message("Begin Animation and Effects");

    //get pagan calendar data from utility/paganCalendar.uc
    var date = getPaganCalendar();
    UI_error_message("Pagan Calendar Data: Year=" + date[DATE_YEAR] + ", Month=" + date[DATE_MONTH] + ", Day=" + date[DATE_DAY_OF_MONTH] + ", Week=" + date[DATE_WEEK] + ", DayName=" + date[DATE_DAY_NAME] + ", TimeName=" + date[DATE_TIME_NAME]);

    //spell script - call map, run anim and sfx
    item_say("@In Wis@");
    script item after 2 ticks {
        nohalt;
        actor frame CAST_1;
        actor frame CAST_2;
        actor frame CAST_1;
        call spellShowMap;
        wait 2;
        actor frame LEAN;
        wait 4;
        actor frame KNEEL;
        sfx 67;
        wait 8;
        actor frame STAND;
    }

    //make bark string
    var day_str = "@It is " + date[DATE_DAY_NAME] + "@";
    var week_month_str = "@The " + date[DATE_WEEK] + " week of " + date[DATE_MONTH_NAME] + "@";
    var time_str = "@During " + date[DATE_TIME_NAME] + "@";
    var year_str = "@In the year " + date[DATE_YEAR] + "@";

    //bark
    delayedBark(AVATAR, day_str, 25);
    delayedBark(AVATAR, week_month_str, 35);
    delayedBark(AVATAR, time_str, 45);
    delayedBark(AVATAR, year_str, 55);
    delayedBark(DUPRE, "@Magic that sucker, yeah!@", 65);
    delayedBark(IOLO, "@Hell of a trick Avatar!@", 70);

    UI_error_message("End Animation and Effects");
}