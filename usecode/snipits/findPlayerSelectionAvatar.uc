//Exult overrides the default shape of the Avatar.
//It is difficult to handle these, this is an attempt to make it easier to get the new redirected shape.

{
//get avatar ref
var avatar_ref = UI_get_avatar_ref();

//get avatar base shape
var base_shape = UI_get_item_shape(avatar_ref);
UI_error_message("base_shape is: " + base_shape);

//get player's selected avatar sex
var avatar_s = UI_get_npc_prop(avatar_ref, 10); // Property 10 = sex
UI_error_message("sex is: " + avatar_s);

//get player's selected avatar hue
var avatar_hue = UI_get_skin_colour(avatar_ref); // Verify intrinsic name
UI_error_message("hue is: " + avatar_hue);

//magic offset
var offset = 307 - (267 * avatar_s); 
UI_error_message("offset is: " + offset);

//calc player's selected avatar shape object
var avatar_redirected_shape = base_shape + offset - (2 * avatar_hue);
UI_error_message("avatar_redirected_shape is: " + avatar_redirected_shape);
}
