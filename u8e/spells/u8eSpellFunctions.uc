// u8eSpellFunctions.uc

void spellClearFlag object#() ()
{
    clear_item_flag(event);
}

void spellSetFlag object#() ()
{
    set_item_flag(event);
}

void spellShowMap object#() ()
{
    var map_shp = 22;
    var show_location = true;
    UI_display_map_ex(map_shp, show_location);
}