//theurgyAerialServant.uc

void theurgyAerialServantWait object#() () {  //make servant wait
    UI_error_message("theurgyAerialServantWait called");
    item->set_schedule_type(WAIT);  //set servent(item) schedule to WAIT flag 15
    UI_error_message("set servant schedule to WAIT(15)");
    var waitSchedule = item->get_schedule_type(); //check schedule flag
    UI_error_message("current servant schedule: " + waitSchedule);
}


void theurgyAerialServantHound object#() () {  //make servant follow the avatar - party not required
    UI_error_message("theurgyAerialServantHound called");
    item->set_schedule_type(HOUND);  //set servent(item) schedule to HOUND flag 9
    UI_error_message("set servant schedule to HOUND(9)");
    var houndSchedule = item->get_schedule_type(); //check schedule flag
    UI_error_message("current servant schedule: " + houndSchedule);
}


void theurgyAerialServantDebugger object#()() {
}

void theurgyAerialServant object#() () {  //main function
    UI_error_message("theurgyAerialServant called");
    var caster = item;
    var startPos;

    //start position of caster item & temporary checking
    if (caster && UI_is_npc(caster)) {
        startPos = UI_get_object_position(caster);
        UI_error_message("startPos is caster");
    } else {
        startPos = UI_get_object_position(AVATAR);
        UI_error_message("startPos is avatar");
    }

    //validate startPos
    if (!startPos || UI_get_array_size(startPos) < 3) {
        UI_error_message("Error: Failed to get start position!");
        return;
    }

    //coordinate elements
    var start_x = startPos[1]; // x-coordinate
    var start_y = startPos[2]; // y-coordinate
    var start_z = startPos[3]; // z-coordinate
    UI_error_message("startPos (x,y,z): " + start_x + "," + start_y + "," + start_z);

    //create the Aerial Servant npc
    var servant = UI_create_new_object(SHAPE_AERIAL_SERVANT);
        if (!servant) {
        UI_error_message("Error: Servant creation failed");
        return;
    }

    //try to place servant in a nearby free position
    var k = 0;
    var placed = false;

    while (k < 3) {
        var i = k - 1;
        var m = 0;
        while (m < 3) {
            var j = m - 1;
            if (i != 0 || j != 0) { //skip the item/caster position
                var newpos = [start_x + i, start_y + j, start_z];
                if (UI_is_not_blocked(newpos, SHAPE_AERIAL_SERVANT, 0)) {
                    UI_set_last_created(servant);
                    UI_update_last_created(newpos); //place it function
                    placed = true;
                    UI_error_message("Aerial Servant placed at: " + newpos[1] + "," + newpos[2] + "," + newpos[3]);
                    break;
                }
            }
            m = m + 1;
        }
        if (placed) {
            break;
        }
        k = k + 1;
    }

    //handle failure to place the servant
    if (!placed) {
        UI_error_message("No free position found");
        UI_remove_item(servant); //just in case
    } else {
        UI_error_message("Aerial Servant creation completed successfully");
    }

    //handle placed servent schedule
    if (placed) {
        if (UI_get_item_flag(servant, DONT_MOVE)) {
            UI_error_message("Clearing DONT_MOVE flag");
            UI_set_item_flag(servant, DONT_MOVE, false); // just in case
        }
        servant->set_schedule_type(HOUND); //follow the avatar when npc is outside party
        UI_error_message("set servant schedule to HOUND(9)"); //set servent schedule to HOUND flag 9
        var houndSchedule = servant->get_schedule_type();
        UI_error_message(" current servant schedule: " + houndSchedule); //check schedule flag
}


}

//conversation function
void theurgyAerialServantConversation shape#(SHAPE_AERIAL_SERVANT) () {
    UI_error_message("theurgyAerialServantConversation called");    
    //var conv options
    var av_1st_greet;
    var npc_1st_greet;
    var npc_2nd_greet;
    var avatar_goodbye;
    var npc_goodbye;

    if (event == DOUBLECLICK) {
        //initial greetings
        av_1st_greet = "@Greetings, servant!@";
        npc_1st_greet = "@I am thy Aerial Servant, here to obey.@";
        //av_2nd_greet = "@What dost thou require?@";
        npc_2nd_greet = "@Command me, master.@";

        //choose face for servant (272)
        UI_show_npc_face(AERIAL_SERVANT_FACE, 0);

        //start the conversation
        item.say(npc_1st_greet);
        AVATAR->say(av_1st_greet);
        //item.say(npc_2nd_greet);
        //AVATAR->say(av_2nd_greet);

        //conv tree
        var options = ["name", "job", "fetch", "use", "move", "follow", "dismiss", "wtf", "bye"];
        converse(options) {
            case "name" (remove):
                say("@I am an Aerial Servant, an ethereal being bound to thy will.@");

            case "job" (remove):
                say("@My purpose is to serve thee, fetching items or aiding as thou commandest.@");
                add(["fetch", "move", "use", "dismiss"]);

            case "fetch" (remove):
                say("@What dost thou wish me to fetch? Name it, and I shall seek it.@");
                //move npc to object, pickup, return, drop or pass obj to av inv?
            
            case "use" (remove):
                say("@What object dost thou decree I wield? Name it, and I shall employ it as thou wilt.@");
                //move npc to target object, npc manipulate target object, or
                //npc cast telekinesis on target object

            case "move" (remove):
                say("@Whither dost thou bid me go? Speak the place, and I shall hasten.@");
                AERIAL_SERVANT_FACE.hide();
                
                UI_error_message("move conversation selected");
                var moveToTarget = UI_click_on_item();
                    if (!moveToTarget || UI_get_array_size(moveToTarget) < 4)
                    {
                        UI_error_message("invalid target!");
                        return;
                    }

                var moveToTarget_x = moveToTarget[2]; //x
                var moveToTarget_y = moveToTarget[3]; //y
                var moveToTarget_z = moveToTarget[4]; //z
                UI_error_message("moveToTarget pos (x,y,z): " + moveToTarget_x + "," + moveToTarget_y + "," + moveToTarget_z);

                var targetPos = [moveToTarget_x, moveToTarget_y, moveToTarget_z];

                //initiate movement to targetPos and call WAIT callback when complete
                UI_si_path_run_usecode(item, targetPos, 0, item, theurgyAerialServantWait, false);
                UI_set_path_failure(theurgyAerialServantHound, item, 0);
                UI_error_message("Commanded servant to move to " + targetPos[1] + "," + targetPos[2] + "," + targetPos[3]);
                break;

                /*
                may not need if path_failure logic works

                if (UI_is_dest_reachable(item, targetPos)) {
                    UI_error_message("Commanded servant to move to " + targetPos[1] + "," + targetPos[2] + "," + targetPos[3]);
                } else {
                    UI_error_message("Destination unreachable");
                    say("@I cannot reach that location.@");
                    item->set_schedule_type(HOUND); //just in case
                    }
                
                */

            case "follow" (remove):
                say("@I shall follow thee.@");
                item->set_schedule_type(HOUND); //re-follow
                break;       


            case "dismiss" (remove):
                say("@As thou wish, I shall depart.@");
                script item after 1 ticks remove; //remove the npc
                break;

            case "bye":
                say("@Farewell, until thou callest again.@");
                //avatar_goodbye = "@Safe travels, servant.@";
                //npc_goodbye = "@I return to the ether.@";
                //AVATAR->say(avatar_goodbye);
                //item.say(npc_goodbye);
                break;

            case "wtf" (remove):
                say("@Strigator la cer!@");
                script item after 1 ticks theurgyAerialServantDebugger;                            
                break;
        }
    }
}


/*

TEST OBJECT HANDLING

void theurgyAerialServant object#() () {
    UI_error_message("theurgyAerialServant starting");
    var target = UI_click_on_item();
    UI_error_message("oooooooooooooooooooooooooooooooo");
    if (target[1] == 0) {
        UI_error_message("Clicked on a tile at (" + target[2] + ", " + target[3] + ", " + target[4] + ")");
    } else {
        var target_shape = target[1]->get_item_shape();
        UI_error_message("Clicked on object with shape " + target_shape + " at (" + target[2] + ", " + target[3] + ", " + target[4] + ")");
        UI_error_message("Target shape identified: " + target_shape);
        var asUnusables = [SHAPE_LOOM, SHAPE_SPINNING_WHEEL, SHAPE_BUCKET, SHAPE_CASK, SHAPE_WELL, SHAPE_CHAIR, SHAPE_BEDROLL, SHAPE_ORB];
        UI_error_message("asUnusables array: " + asUnusables);
        var asUsables = [SHAPE_SWITCH, SHAPE_LEVER];
        UI_error_message("asUsables array: " + asUsables);
        UI_error_message("Evaluating shape " + target_shape + " against arrays");
        if (target_shape in asUsables) {
            UI_error_message("Shape " + target_shape + " found in asUsables");
            UI_error_message("Triggering usecode with default event or");
            UI_error_message("Cast Telekinesis");
            script item
                call get_usecode_fun();
        } else if (!(target_shape in asUnusables)) {
            UI_error_message("Shape " + target_shape + " not in asUnusables");
            UI_error_message("Triggering usecode with DOUBLECLICK event or");
            UI_error_message("Cast Fetch");
            script item
                call get_usecode_fun(), DOUBLECLICK;
        } else {
            UI_error_message("Shape " + target_shape + " is in asUnusables");
            UI_error_message("Cant Use Send Bark");

        }

    }
UI_error_message("oooooooooooooooooooooooooooooooo");    
}

    


        //var startPos = [target[2], target[3], target[4]];
        //var new_obj = UI_create_new_object2(SHAPE_AERIAL_SERVANT, startPos);


        //SHAPE_LOOM - doesn't seem to work for Telekinesis,
        user needs to doubleclick thread to use loom as they need
        thread in their containers for use - classify as unusable
        for now

        //missing unusables:
        //SHAPE_THREAD
        //SHAPE_WOOL
        //SHAPE_KITE
        //SHAPE_BELLOWS
        //SHAPE_KEG
        //SHAPE_STRENGTH_TESTER
        //SHAPE_BED_HORIZONTAL
        //SHAPE_BED_VERTICAL
        //SHAPE_WELLBASE

        //missing usables:
        //SHAPE_WINCH_HORIZONTAL
        //SHAPE_WINCH_VERTICAL

        */