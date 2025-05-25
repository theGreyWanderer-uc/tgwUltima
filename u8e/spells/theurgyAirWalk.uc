//theurgyAirWalk.uc

//function to compute absolute value - testing
var abs(var num)
{
    if (num < 0)
        return -num;
    else
        return num;
}

//function to make the caster vanish
void vanishAvatar object#() ()
{
    UI_error_message("vanishAvatar called");
    item->set_item_flag(22); //SI_DONT_RENDER - vanish
    UI_error_message("AVATAR vanished!");
}

//function to make the caster reappear
void reappearAvatar object#() ()
{
    UI_error_message("reappearAvatar called");
    item->clear_item_flag(22); //clear SI_DONT_RENDER - reappear
    UI_error_message("AVATAR reappeared!");
}

//function to teleport and reappear
void teleportAndReappear object#() ()
{
    var caster = item;
    UI_error_message("teleportAndReappear called");
    var nearby = UI_find_nearby(caster, 247, 50, 0);
    var marker = false;

    if (nearby)
    {
        for (obj in nearby)
        {
            if (obj->get_item_shape() == 247 && 
                obj->get_item_flag(22) && 
                obj->get_item_flag(18))
            {
                marker = obj;
                break;
            }
        }
    }

    if (marker)
    {
        var target_x = marker->get_npc_prop("strength");
        var target_y = marker->get_npc_prop("dexterity");
        var target_z = marker->get_npc_prop("intelligence");
        
        //tp the caster to the target location
        UI_move_object(caster, [target_x, target_y, target_z], false);
        UI_error_message("Caster teleported to: x=" + target_x + ", y=" + target_y + ", z=" + target_z);

        //tp party with caster
        var party = UI_get_party_list();
        var offsets = [[0,1], [1,0], [0,-1], [-1,0], [1,1], [1,-1], [-1,1], [-1,-1]];
        var i = 0;
        for (member in party)
        {
            if (member != caster) //skip the caster
            {
                var offset = offsets[i % UI_get_array_size(offsets)];
                var member_x = target_x + offset[1];
                var member_y = target_y + offset[2];
                UI_move_object(member, [member_x, member_y, target_z], false);
                UI_error_message("Party member " + member + " moved to: x=" + member_x + ", y=" + member_y + ", z=" + target_z);
                i = i + 1;
            }
        }

        caster->reappearAvatar(); //reappear the caster
        UI_remove_item(marker); //cleanup the marker jump npc
    }
    else
    {
        UI_error_message("No JUMP1 NPC found! 2");
    }
}

//function to jump/launch the caster
void launchAvatarWrapper object#() ()
{
    var caster = item;
    UI_error_message("launchAvatarWrapper called");
    var nearby = UI_find_nearby(caster, 247, 50, 0); //locate marker npc
    var marker = false;

    if (nearby)
    {
        for (obj in nearby)
        {
            if (obj->get_item_shape() == 247 && 
                obj->get_item_flag(22) && 
                obj->get_item_flag(18))
            {
                marker = obj;
                break;
            }
        }
    }

    if (marker)
    {
        var target_x = marker->get_npc_prop("strength"); //use str for x
        var target_y = marker->get_npc_prop("dexterity"); //use dex for y
        var target_dir = marker->get_npc_prop("training"); //use train for dir
        var start_pos = UI_get_object_position(caster);
        var start_x = start_pos[1];
        var start_y = start_pos[2];
        
        UI_error_message("start_x: " + start_x + ", start_y: " + start_y);
        UI_error_message("target_x: " + target_x + ", target_y: " + target_y);
        UI_error_message("Launching to " + target_x + "," + target_y + " dir " + target_dir);
        
        //get Avatar's redirected shape - u8eCommonFunctions.uc
        var avatar_redirected_shape = getAvatarRedirectedShape();
        UI_error_message("avatar_redirected_shape is: " + avatar_redirected_shape);

        //fire a projectile of redirected shape in direction from caster to target coords
        UI_fire_projectile(caster, target_dir, avatar_redirected_shape, 5, target_x, target_y);
        UI_error_message("Firing redirected shape");
        
        //calc for distance/time
        var dx = abs(target_x - start_x);
        UI_error_message("dx: " + dx);
        var dy = abs(target_y - start_y);
        UI_error_message("dy: " + dy);
        
        var distance = dx + dy;
        UI_error_message("distance: " + distance);
        
        var speed = 5;
        UI_error_message("speed: " + speed);
        
        var flight_time = (distance / speed) * 1;
        UI_error_message("flight_time: " + flight_time);

        script caster after flight_time ticks call teleportAndReappear;
    }
    else
    {
        UI_error_message("launchAvatarWrapper: No JUMP1 NPC found! 1");
    }
}

void projectileCleanup object#()()
{
    UI_error_message("projectileCleanup called");

    //get Avatar's redirected shape - u8eCommonFunctions.uc
    var avatar_redirected_shape = getAvatarRedirectedShape();
    UI_error_message("avatar_redirected_shape is: " + avatar_redirected_shape);

    //get objects around caster/item
    var nearby = UI_find_nearby(item, -359, 50, 0xF0);
    UI_error_message("Debugging objects within 5 tiles of the caster:");

    if (UI_get_array_size(nearby) == 0)
    {
        UI_error_message("No objects found.");
    }
    else
    {
        var obj;
        for (obj in nearby)
        {
            var shape = UI_get_item_shape(obj);
            var pos = UI_get_object_position(obj);
            
            if (shape == avatar_redirected_shape && obj != UI_get_avatar_ref())
            {
                UI_error_message("Match found: Object shape " + shape + " at (" + pos[1] + ", " + pos[2] + ", " + pos[3] + ")");
                UI_remove_item(obj); //if redirected shape located nearby then remove it
            }
        }
    }
    UI_error_message("End of list.");
}

//main air walk spell function
void theurgyAirWalk object#() ()
{
    var caster = AVATAR;
    UI_error_message("theurgyAirWalk called");    
    UI_error_message("Caster ID: " + caster);
    var start_pos = UI_get_object_position(caster);
    if (!start_pos || UI_get_array_size(start_pos) < 3)
    {
        UI_error_message("Error: Failed to get start position!");
        return;
    }
    var start_x = start_pos[1]; // x
    var start_y = start_pos[2]; // y
    UI_error_message("Start pos (x,y): " + start_x + "," + start_y);
    UI_error_message("Click a destination for Air Walk!");
    var target = UI_click_on_item(); //returns [obj, x, y, z]
    if (!target || UI_get_array_size(target) < 4)
    {
        UI_error_message("Air Walk canceled or invalid target!");
        return;
    }
    var target_obj = target[1]; // obj
    var target_x = target[2];   // x
    var target_y = target[3];   // y
    var target_z = target[4];   // z
    var target_dir = UI_find_direction(start_pos, target); //direction 0-7
    UI_error_message("Target object: " + target_obj);
    UI_error_message("Target pos (x,y,z): " + target_x + "," + target_y + "," + target_z);
    UI_error_message("Calc direction: " + target_dir);
    
    //create new NPC "JUMP1" with shape 247 to use as target marker
    var marker = UI_create_new_object(247);
    if (marker)
    {
        marker->set_item_flag(22); //SI_DONT_RENDER - don't show the new NPC
        //marker->set_item_flag(18); //remember to re-check this with detection
        
        //move NPC to target coordinates
        UI_update_last_created([target_x, target_y, target_z]);
        
        //set NPC properties to target values
        marker->set_npc_prop("strength", target_x);
        marker->set_npc_prop("dexterity", target_y);
        marker->set_npc_prop("intelligence", target_z);
        marker->set_npc_prop("training", target_dir);
        
        //debug NPC properties after setting
        var strength = marker->get_npc_prop("strength");
        var dexterity = marker->get_npc_prop("dexterity");
        var intelligence = marker->get_npc_prop("intelligence");
        var training = marker->get_npc_prop("training");
        UI_error_message("Debug JUMP1 strength (x): " + strength);
        UI_error_message("Debug JUMP1 dexterity (y): " + dexterity);
        UI_error_message("Debug JUMP1 intelligence (z): " + intelligence);
        UI_error_message("Debug JUMP1 training (dir): " + training);
        
        //script block
        script caster
        {
            nohalt;
            face target_dir;
            wait 1;
            actor frame LEAN;
            wait 3;
            actor frame KNEEL;
            actor frame RAISE_2H;
            wait 3;
            call vanishAvatar;       //make caster vanish
            wait 1;                  //pause before launch
            call launchAvatarWrapper; //launch caster
            wait 5; 
            call projectileCleanup; //cleanup fired projectile shape
            actor frame LEAN;
            actor frame KNEEL;
            actor frame STAND;
        }
    }
    else
    {
        UI_error_message("Failed to create JUMP1 NPC!");
        return;
    }

}
