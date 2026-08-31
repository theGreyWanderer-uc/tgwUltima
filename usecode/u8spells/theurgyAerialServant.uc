//theurgyAerialServant.uc

// Persists a target object reference between conversation click and movement callbacks.
// mode 0 = read, mode 1 = write.
var aerialServantTargetStore(var mode, var val) {
    static var stored;
    if (mode == 1) { stored = val; }
    return stored;
}

// Persists a fetched item's properties after it has been removed from the world.
// Stored as [shape, frame, quality, quantity].
// mode 0 = read (returns array), mode 1 = write (val must be [shape, frame, quality, quantity]).
var aerialServantItemStore(var mode, var val) {
    static var stored;
    if (mode == 1) { stored = val; }
    return stored;
}

// Guards the fetch/deliver round-trip so no other command can interrupt it mid-transit.
// mode 0 = read, mode 1 = write.
var aerialServantBusyStore(var mode, var val) {
    static var stored;
    if (mode == 1) { stored = val; }
    return stored;
}

// Tracks whether the servant has already given its 1st-time greeting this summon.
// mode 0 = read, mode 1 = write.
var aerialServantGreetedStore(var mode, var val) {
    static var stored;
    if (mode == 1) { stored = val; }
    return stored;
}

// Holds the temporary visual-only clone of the fetched item while the servant "carries" it.
// mode 0 = read, mode 1 = write.
var aerialServantCarryStore(var mode, var val) {
    static var stored;
    if (mode == 1) { stored = val; }
    return stored;
}

// Counts watchdog ticks so it self-terminates instead of rescheduling forever.
// mode 0 = read, mode 1 = write.
var aerialServantWatchdogStore(var mode, var val) {
    static var stored;
    if (mode == 1) { stored = val; }
    return stored;
}

// Countdown of ticks remaining before the servant auto-dismisses.
// mode 0 = read, mode 1 = write.
var aerialServantExpireStore(var mode, var val) {
    static var stored;
    if (mode == 1) { stored = val; }
    return stored;
}

// Adds seconds (converted to ticks) to the expire countdown - called whenever a
// command (fetch/move/use) is issued, so the servant can't expire mid-errand.
var aerialServantExtendExpire(var seconds) {
    aerialServantExpireStore(1, aerialServantExpireStore(0, 0) + (seconds * 10));
    return 0;
}

// Chebyshev tile distance between two [x,y,z] positions (ignores z).
var tileDistance(var posA, var posB) {
    var dx = posA[1] - posB[1];
    var dy = posA[2] - posB[2];
    if (dx < 0) { dx = 0 - dx; }
    if (dy < 0) { dy = 0 - dy; }
    if (dx > dy) { return dx; }
    return dy;
}

// Self-rescheduling lifespan timer, independent of the watchdog (which only
// runs while a command is active). Also dismisses early if the Avatar strays
// more than 128 tiles away. Refuses to expire while a fetch is in flight or
// the carry-visual is still out, instead granting a short grace period and
// rechecking, so the servant can't vanish mid-errand.
void theurgyAerialServantExpireTick object#() () {
    var avatarPos = UI_get_object_position(AVATAR);
    var pos = UI_get_object_position(item);
    var tooFar = false;
    if (avatarPos && pos && UI_get_array_size(avatarPos) >= 3 && UI_get_array_size(pos) >= 3) {
        tooFar = tileDistance(avatarPos, pos) > 128;
    }

    var remaining = aerialServantExpireStore(0, 0) - 10;
    if (!tooFar && remaining > 0) {
        aerialServantExpireStore(1, remaining);
        script item after 10 ticks {
            nohalt;
            call theurgyAerialServantExpireTick;
        }
        return;
    }
    if (aerialServantBusyStore(0, 0) || aerialServantCarryStore(0, 0)) {
        //UI_error_message("Aerial Servant expire/distance check delayed - busy/carrying");
        aerialServantExpireStore(1, 10);
        script item after 10 ticks {
            nohalt;
            call theurgyAerialServantExpireTick;
        }
        return;
    }
    if (tooFar) {
        //UI_error_message("Aerial Servant too far from Avatar - dismissing");
        item_say("@Too far afield, master - I return to the ether.@");
    } else {
        //UI_error_message("Aerial Servant lifespan expired - dismissing");
        item_say("@My time is spent; I return to the ether.@");
    }
    UI_remove_npc_face0();
    script item after 1 ticks remove;
}

// Floats the carried-item visual just above the servant so it reads as "held" rather than sitting on the ground.
var theurgyAerialServantCarryOffsetPos(var pos) {
    return [pos[1], pos[2], pos[3] + 2];
}

// DIAGNOSTIC: heartbeat logging the servant's live position/schedule every 2 ticks,
// indefinitely, regardless of schedule - if this stops printing entirely, the freeze is in
// native engine code (not usecode), and the last printed tick pinpoints when it happened.
// Also repositions the carried-item visual (see theurgyAerialServantFetch) here rather than
// in its own separate script chain - a standalone chain was observed to silently stop
// mid-transit on longer/bumpier return paths, likely killed by the engine's own internal
// scripts for path retry/blocked handling (Usecode_script::start() terminates other
// non-nohalt scripts on the same object); this loop has proven reliable across all prior
// testing, so folding the carry-follow into it avoids running a second, more fragile chain.
void theurgyAerialServantWatchdog object#() () {
    var n = aerialServantWatchdogStore(0, 0) + 1;
    aerialServantWatchdogStore(1, n);
    var pos = UI_get_object_position(item);
    var sched = item->get_schedule_type();
    //UI_error_message("watchdog tick " + n + ": servant pos (x,y,z): " + pos[1] + "," + pos[2] + "," + pos[3] + " schedule: " + sched);
    var carryObj = aerialServantCarryStore(0, 0);
    if (carryObj && pos && UI_get_array_size(pos) >= 3) {
        UI_move_object(carryObj, theurgyAerialServantCarryOffsetPos(pos), false);
    }
    script item after 2 ticks {
        nohalt;
        call theurgyAerialServantWatchdog;
    }
}

// Path-failure fallback for the fetch leg: abandons the fetch cleanly so the
// busy flag can't be left stuck forever.
void theurgyAerialServantFetchAbort object#() () {
    //UI_error_message("theurgyAerialServantFetchAbort called - path to target failed");
    aerialServantTargetStore(1, 0);
    aerialServantBusyStore(1, false);
    item->set_schedule_type(WAIT); //don't auto-resume following - see note on HOUND usage below
}

// Deliver callback: servant has returned to Avatar.
// Recreates the fetched item via UI_add_party_items, which tries Avatar first,
// then companions, then drops at Avatar's feet — item is never lost.
void theurgyAerialServantDeliver object#() () {
    //UI_error_message("theurgyAerialServantDeliver called");
    var props = aerialServantItemStore(0, 0);
    if (props && UI_get_array_size(props) >= 4) {
        var shape    = props[1];
        var frame    = props[2];
        var quality  = props[3];
        var quantity = props[4];
        if (quantity < 1) { quantity = 1; }
        var result  = UI_add_party_items(quantity, shape, quality, frame, false);
        var arr_sz  = UI_get_array_size(result);
        var ground  = result[arr_sz];
        if (ground > 0) {
            item_say("@I set it upon the ground, master - none could bear its weight.@");
        } else if (arr_sz >= 3) {
            item_say("@Thy companion carries it for thee, master.@");
        } else {
            item_say("@Here is what thou hast asked for, master.@");
        }
    } else {
        //UI_error_message("theurgyAerialServantDeliver: no stored item props");
    }
    var carryObj = aerialServantCarryStore(0, 0);
    if (carryObj) {
        UI_remove_item(carryObj);
        aerialServantCarryStore(1, 0);
    }
    aerialServantItemStore(1, 0); //clear so a stray re-entry can't redeliver stale props
    aerialServantBusyStore(1, false);
    item->set_schedule_type(WAIT); //don't auto-resume following
}

// Fallback for a return-path action that silently stalls (neither arrives nor
// triggers its path-failure callback) - forces delivery if still busy after the timeout.
void theurgyAerialServantDeliverFallback object#() () {
    if (aerialServantBusyStore(0, 0)) {
        //UI_error_message("return path stalled - forcing delivery");
        item->theurgyAerialServantDeliver(); //explicit itemref - same object, just silences the ucc warning
    }
}

// Finds a free tile near basePos, expanding outward ring by ring (never returns the
// center tile itself - useful for pathing next to an actor rather than onto its tile).
// Returns [x,y,z], or 0 if nothing free within radius 5.
var findFreeSpotNear(var basePos, var shape) {
    var radius = 1;
    while (radius <= 5) {
        var i = 0 - radius;
        while (i <= radius) {
            var j = 0 - radius;
            while (j <= radius) {
                if (i > 0 - radius && i < radius && j > 0 - radius && j < radius) {
                    j = j + 1;
                    continue; //interior tile, already checked at a smaller radius
                }
                var newpos = [basePos[1] + i, basePos[2] + j, basePos[3]];
                if (UI_is_not_blocked(newpos, shape, 0)) {
                    return newpos;
                }
                j = j + 1;
            }
            i = i + 1;
        }
        radius = radius + 1;
    }
    return 0;
}

// Commands the return path. Deferred by 1 tick from theurgyAerialServantFetch rather
// than called synchronously - issuing a new path action on the same NPC from directly
// inside the prior path action's own completion callback let the engine's action
// cleanup silently stomp the new action (this was the actual return-leg stall cause).
void theurgyAerialServantCommandReturn object#() () {
    var avatarPos = UI_get_object_position(AVATAR);
    var returnPos = findFreeSpotNear(avatarPos, SHAPE_AERIAL_SERVANT);
    if (!returnPos) {
        returnPos = [avatarPos[1], avatarPos[2], avatarPos[3]]; //no free tile found nearby - fall back to avatar's exact tile
    }
    UI_si_path_run_usecode(item, returnPos, 0, item, theurgyAerialServantDeliver, false);
    UI_set_path_failure(theurgyAerialServantDeliver, item, 0); //force delivery even if the return path fails, so the item isn't lost
    //UI_error_message("Return path commanded to " + returnPos[1] + "," + returnPos[2] + "," + returnPos[3]);
    aerialServantWatchdogStore(1, 0);
    script item after 2 ticks {
        nohalt;
        call theurgyAerialServantWatchdog;
    }
    script item after 60 ticks {
        nohalt;
        call theurgyAerialServantDeliverFallback;
    }
}

// Fetch callback: servant has arrived at target position.
// Reads item properties, removes it from the world (item enters "transit"),
// then paths back to Avatar for delivery.
void theurgyAerialServantFetch object#() () {
    //UI_error_message("theurgyAerialServantFetch called");
    var targetObj = aerialServantTargetStore(0, 0);
    if (targetObj) {
        var shape    = targetObj->get_item_shape();
        var frame    = targetObj->get_item_frame();
        var quality  = targetObj->get_item_quality();
        var quantity = targetObj->get_item_quantity(0);
        //UI_error_message("Fetching shape=" + shape + " frame=" + frame + " quality=" + quality + " qty=" + quantity);
        aerialServantItemStore(1, [shape, frame, quality, quantity]);
        targetObj->remove_item();
        //UI_error_message("Item removed from world, servant returning to avatar");

        // Visual only - a clone the servant visibly "carries" until delivery; the real item
        // stays in aerialServantItemStore and is recreated for real in theurgyAerialServantDeliver.
        // Repositioned every watchdog tick (see theurgyAerialServantWatchdog) rather than its own
        // script chain, which was observed to silently die mid-transit on some return paths.
        var carryObj = UI_create_new_object(shape);
        if (carryObj) {
            carryObj->set_item_frame(frame);
            carryObj->set_item_quality(quality);
            UI_update_last_created(theurgyAerialServantCarryOffsetPos(UI_get_object_position(item)));
            aerialServantCarryStore(1, carryObj);
        }

        script item after 1 ticks {
            nohalt;
            call theurgyAerialServantCommandReturn;
        }
    } else {
        //UI_error_message("theurgyAerialServantFetch: no stored target");
        aerialServantBusyStore(1, false);
        item->set_schedule_type(WAIT); //don't auto-resume following
    }
}


// Use callback: servant has arrived at target position.
// Fires the stored target item's usecode, then resumes following.
void theurgyAerialServantUse object#() () {
    //UI_error_message("theurgyAerialServantUse called");
    var targetObj = aerialServantTargetStore(0, 0);
    if (targetObj) {
        // get_usecode_fun() needs an explicit object arg - a bare call defaults to
        // 'item' (the servant itself), which re-fired OUR OWN conversation instead
        // of the target's usecode.
        script targetObj {
            call targetObj->get_usecode_fun(), DOUBLECLICK;
        }
        //UI_error_message("Servant used item");
    } else {
        //UI_error_message("theurgyAerialServantUse: no stored target");
    }
    item->set_schedule_type(WAIT); //don't auto-resume following
}


void theurgyAerialServantWait object#() () {  //make servant wait
    //UI_error_message("theurgyAerialServantWait called");
    item->set_schedule_type(WAIT);  //set servent(item) schedule to WAIT flag 15
    //UI_error_message("set servant schedule to WAIT(15)");
    var waitSchedule = item->get_schedule_type(); //check schedule flag
    //UI_error_message("current servant schedule: " + waitSchedule);
}


void theurgyAerialServant object#() () {  //main function
    //UI_error_message("theurgyAerialServant called");
    var caster = item;

    //abort if a servant already exists anywhere in the loaded area (half a superchunk radius)
    //search around the caster, not always the Avatar, in case an ally cast this spell
    var searchPos;
    if (caster && UI_is_npc(caster)) {
        searchPos = UI_get_object_position(caster);
    } else {
        searchPos = UI_get_object_position(AVATAR);
    }
    var existingServants = UI_find_nearby(searchPos, SHAPE_AERIAL_SERVANT, 128, MASK_NONE);
    if (existingServants && UI_get_array_size(existingServants) > 0) {
        //UI_error_message("Aerial Servant already summoned - aborting cast");
        item_say("@It is already summoned!@");
        return;
    }

    if (!spendMagicMana(caster, 5)) {
        return;
    }

    item_say("@Kal Ort Xen@");
    var startPos;

    //start position of caster item & temporary checking
    if (caster && UI_is_npc(caster)) {
        startPos = UI_get_object_position(caster);
        //UI_error_message("startPos is caster");
    } else {
        startPos = UI_get_object_position(AVATAR);
        //UI_error_message("startPos is avatar");
    }

    //validate startPos
    if (!startPos || UI_get_array_size(startPos) < 3) {
        //UI_error_message("Error: Failed to get start position!");
        return;
    }

    //coordinate elements
    var start_x = startPos[1]; // x-coordinate
    var start_y = startPos[2]; // y-coordinate
    var start_z = startPos[3]; // z-coordinate
    //UI_error_message("startPos (x,y,z): " + start_x + "," + start_y + "," + start_z);

    //create the Aerial Servant npc
    var servant = UI_create_new_object(SHAPE_AERIAL_SERVANT);
        if (!servant) {
        //UI_error_message("Error: Servant creation failed");
        return;
    }

    //try to place servant in a nearby free position, expanding outward ring by ring
    var placed = false;
    var radius = 1;

    while (radius <= 5) {
        var i = 0 - radius;
        while (i <= radius) {
            var j = 0 - radius;
            while (j <= radius) {
                if (i > 0 - radius && i < radius && j > 0 - radius && j < radius) {
                    j = j + 1;
                    continue; //interior tile, already checked at a smaller radius
                }
                var newpos = [start_x + i, start_y + j, start_z];
                if (UI_is_not_blocked(newpos, SHAPE_AERIAL_SERVANT, 0)) {
                    UI_set_last_created(servant);
                    UI_update_last_created(newpos); //place it function
                    placed = true;
                    //UI_error_message("Aerial Servant placed at: " + newpos[1] + "," + newpos[2] + "," + newpos[3]);
                    break;
                }
                j = j + 1;
            }
            if (placed) {
                break;
            }
            i = i + 1;
        }
        if (placed) {
            break;
        }
        radius = radius + 1;
    }

    //handle failure to place the servant
    if (!placed) {
        //UI_error_message("No free position found");
        UI_remove_item(servant); //just in case
        return;
    }

    //UI_error_message("Aerial Servant creation completed successfully");
    if (UI_get_item_flag(servant, DONT_MOVE)) {
        //UI_error_message("Clearing DONT_MOVE flag");
        UI_set_item_flag(servant, DONT_MOVE, false); // just in case
    }
    // HOUND is only ever set via the "follow" conversation command, never automatically here -
    // Exult's Actor::follow() indexes an array by party_id, which is -1 for this non-party NPC.

    var baseDuration = 60; //1 minute in seconds
    var duration = randomSpellDuration(baseDuration, 10); //50-70 seconds
    //UI_error_message("Aerial Servant lifespan: " + duration + " seconds");
    aerialServantExpireStore(1, duration * 10);
    script servant after 10 ticks {
        nohalt;
        call theurgyAerialServantExpireTick;
    }
}

//conversation function
void theurgyAerialServantConversation shape#(SHAPE_AERIAL_SERVANT) () {
    // This shape's usecode is the engine's general dispatcher for this NPC (schedule/proximity/idle
    // ticks too, not just double-click) - bail out immediately for anything else so we don't do
    // real work (or even log) on every AI tick while the servant is following.
    if (event == DOUBLECLICK) {
        //UI_error_message("theurgyAerialServantConversation called - DOUBLECLICK");
        //var conv options
        var av_1st_greet;
        var npc_1st_greet;
        var npc_2nd_greet;
        var avatar_goodbye = "@Safe travels, servant.@";
        var npc_goodbye = "@I return to serve when thou callest.@";

        // Fetch is in flight - refuse to open the menu so it can't be interrupted mid-transit.
        if (aerialServantBusyStore(0, 0)) {
            //UI_error_message("conversation blocked - servant still busy with fetch/return");
            delayedBark(item, "@I am yet upon thine errand, master.@", 1);
            return;
        }

        //initial greetings
        av_1st_greet = "@Greetings, servant!@";
        npc_1st_greet = "@I am thy Aerial Servant, here to obey.@";
        npc_2nd_greet = "@Command me, master.@";

        //choose face for servant (272)
        UI_show_npc_face(AERIAL_SERVANT_FACE, 0);

        //start the conversation - full greeting only the first time, short prompt after that
        if (!aerialServantGreetedStore(0, 0)) {
            item.say(npc_1st_greet);
            AVATAR->say(av_1st_greet);
            aerialServantGreetedStore(1, true);
        } else {
            item.say(npc_2nd_greet);
        }

        //conv tree
        var options = ["name", "fetch", "move", "use", "dismiss", "follow", "bye"];
        converse(options) {
            case "name" (remove):
                say("@I am an Aerial Servant, an ethereal being bound to thy will.@");

            case "fetch" (remove):
                say("@What dost thou wish me to fetch? Name it, and I shall seek it.@");
                AERIAL_SERVANT_FACE.hide();

                //UI_error_message("fetch conversation selected");
                var fetchTarget = UI_click_on_item();
                if (!fetchTarget || UI_get_array_size(fetchTarget) < 4) {
                    //UI_error_message("fetch: invalid target");
                    return;
                }
                if (fetchTarget[1] == 0) {
                    //UI_error_message("fetch: clicked tile, not an object");
                    break;
                }

                if (fetchTarget[1]->get_item_weight() > 10) {
                    //UI_error_message("fetch: item too heavy - weight " + fetchTarget[1]->get_item_weight());
                    item_say("@Its weight defies my grasp, master.@");
                    break;
                }

                aerialServantTargetStore(1, fetchTarget[1]);
                aerialServantBusyStore(1, true);

                var fetch_x = fetchTarget[2];
                var fetch_y = fetchTarget[3];
                var fetch_z = fetchTarget[4];
                var itemPos = [fetch_x, fetch_y, fetch_z];
                // Path to a free tile NEXT TO the item, not onto the item's own tile - many
                // items (e.g. coin stacks) sit on a tile that isn't itself walkable, which made
                // the pathfinder correctly fail even for short, unobstructed distances.
                var fetchPos = findFreeSpotNear(itemPos, SHAPE_AERIAL_SERVANT);
                if (!fetchPos) {
                    fetchPos = itemPos; //no free adjacent tile found - fall back to the item's own tile
                }

                UI_si_path_run_usecode(item, fetchPos, 0, item, theurgyAerialServantFetch, false);
                UI_set_path_failure(theurgyAerialServantFetchAbort, item, 0);
                //UI_error_message("Commanded servant to fetch item at " + fetch_x + "," + fetch_y + "," + fetch_z);
                aerialServantExtendExpire(60);
                aerialServantWatchdogStore(1, 0);
                script item after 2 ticks {
                    nohalt;
                    call theurgyAerialServantWatchdog;
                }
                break;
            
            case "use" (remove):
                say("@What object dost thou decree I wield? Name it, and I shall employ it as thou wilt.@");
                AERIAL_SERVANT_FACE.hide();

                //UI_error_message("use conversation selected");
                var useTarget = UI_click_on_item();
                if (!useTarget || UI_get_array_size(useTarget) < 4) {
                    //UI_error_message("use: invalid target");
                    return;
                }
                if (useTarget[1] == 0) {
                    //UI_error_message("use: clicked tile, not an object");
                    break;
                }

                aerialServantTargetStore(1, useTarget[1]);

                var use_x = useTarget[2];
                var use_y = useTarget[3];
                var use_z = useTarget[4];
                var usePos = [use_x, use_y, use_z];

                UI_si_path_run_usecode(item, usePos, 0, item, theurgyAerialServantUse, false);
                UI_set_path_failure(theurgyAerialServantWait, item, 0);
                //UI_error_message("Commanded servant to use item at " + use_x + "," + use_y + "," + use_z);
                aerialServantExtendExpire(60);
                aerialServantWatchdogStore(1, 0);
                script item after 2 ticks {
                    nohalt;
                    call theurgyAerialServantWatchdog;
                }
                break;

            case "move" (remove):
                say("@Whither dost thou bid me go? Speak the place, and I shall hasten.@");
                AERIAL_SERVANT_FACE.hide();
                
                //UI_error_message("move conversation selected");
                var moveToTarget = UI_click_on_item();
                    if (!moveToTarget || UI_get_array_size(moveToTarget) < 4)
                    {
                        //UI_error_message("invalid target!");
                        return;
                    }

                var moveToTarget_x = moveToTarget[2]; //x
                var moveToTarget_y = moveToTarget[3]; //y
                var moveToTarget_z = moveToTarget[4]; //z
                //UI_error_message("moveToTarget pos (x,y,z): " + moveToTarget_x + "," + moveToTarget_y + "," + moveToTarget_z);

                var targetPos = [moveToTarget_x, moveToTarget_y, moveToTarget_z];

                //initiate movement to targetPos and call WAIT callback when complete
                UI_si_path_run_usecode(item, targetPos, 0, item, theurgyAerialServantWait, false);
                UI_set_path_failure(theurgyAerialServantWait, item, 0);
                //UI_error_message("Commanded servant to move to " + targetPos[1] + "," + targetPos[2] + "," + targetPos[3]);
                aerialServantExtendExpire(60);
                aerialServantWatchdogStore(1, 0);
                script item after 2 ticks {
                    nohalt;
                    call theurgyAerialServantWatchdog;
                }
                break;

            case "follow" (remove):
                say("@I shall follow thee.@");
                item->set_schedule_type(HOUND); //re-follow
                aerialServantWatchdogStore(1, 0);
                script item after 2 ticks {
                    nohalt;
                    call theurgyAerialServantWatchdog;
                }
                break;       


            case "dismiss" (remove):
                say("@As thou wish, I shall depart.@");
                UI_remove_npc_face0();
                aerialServantExpireStore(1, 30000); //prevent the still-scheduled expire loop from firing on the removed item
                script item after 1 ticks remove; //remove the npc
                break;

            case "bye":
                UI_remove_npc_face0();
                sayGoodbye(item, npc_goodbye, avatar_goodbye);
                break;

        }
    }
}