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


//getAvatarRedirectedShape - function to calculate avatar_redirected_shape
//Exult overrides the default shape of the Avatar.
//It is difficult to handle these, this is an attempt to make it easier to get the new redirected shape.
var getAvatarRedirectedShape() {
  var avatar_ref = UI_get_avatar_ref();
  var base_shape = UI_get_item_shape(avatar_ref);
  var avatar_s = UI_get_npc_prop(avatar_ref, 10);
  var avatar_hue = UI_get_skin_colour(avatar_ref);
  var offset = 307 - (267 * avatar_s);
  var avatar_redirected_shape = base_shape + offset - (2 * avatar_hue);
  return avatar_redirected_shape;
}