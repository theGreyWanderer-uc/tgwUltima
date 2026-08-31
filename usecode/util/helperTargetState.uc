//========================//
// TARGET STATE HELPERS   //
//========================//

// Returns 0 for invalid/no target, 1 for a dead NPC, 2 for a corpse/body object,
// and 3 for a living NPC or unrelated object.
var getDeathSpeakTargetState(var target)
{
    if (!target)
    {
        return 0;
    }

    if (UI_is_npc(target))
    {
        if (UI_get_item_flag(target, DEAD))
        {
            return 1;
        }

        return 3;
    }

    if (UI_get_shape_flag(target, SHAPE_FLAG_BODY))
    {
        return 2;
    }

    return 3;
}

// Restores an NPC to full health using Exult's health model:
// current hits = HEALTH, max hits = STRENGTH.
var restoreNpcToFullHealth(var npc)
{
    var maxhp = npc->get_npc_prop(STRENGTH);
    var hps = npc->get_npc_prop(HEALTH);

    if (hps < 1)
    {
        hps = 1;
    }

    var missing = maxhp - hps;
    if (missing > 0)
    {
        npc->set_npc_prop(HEALTH, missing);
    }

    return missing;
}

//returns the direction (N/S/W/E) that the NPC is currently facing
var getFacing (var npc)
{
	var direction;
	var framenum;
	
	framenum = npc->get_item_frame_rot();

	if		(framenum >= EAST_FRAMESET)		direction = EAST;
	else if (framenum >= WEST_FRAMESET)		direction = WEST;
	else if (framenum >= SOUTH_FRAMESET)	direction = SOUTH;
	else direction = NORTH;

	return direction;
}
