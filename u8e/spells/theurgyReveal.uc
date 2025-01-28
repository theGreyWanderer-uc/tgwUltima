void theurgyReveal object#() () {

	var quality = UI_get_item_quality(item);
	var frame = UI_get_item_frame(item);

	UI_error_message("theurgyReveal executing");

	var caster = getOuterContainer(item);
	var curMana = get_npc_prop(MANA);
	UI_error_message("curMana proc eval using -get_npc_prop(MANA) - before checking:" + curMana); 
    
		if (curMana < 5)
		{
			var curMana = get_npc_prop(MANA);
			item_say("@Not enough mana...@");
			var curManaMessage = "curMana proc eval using -get_npc_prop- while failing check:" + curMana;
			UI_error_message(curManaMessage);
			UI_error_message("Not enough mana to cast spell - return");
			return;
		}        




	var findPos = UI_get_object_position(item);
	var offset_x = [-15, -15, -15, -5, -5, -5, 5, 5, 5, 15, 15, 15];
	var offset_y = [-7, 2, 11, -7, 2, 11, -7, 2, 11, -7, 2, 11];
	var dist = 7;
	var counter = 0;
	var revealables = [];

	UI_error_message("----------------------------------");
	UI_error_message("Var findPos: X = " + findPos[0] + ", Y = " + findPos[1]);
	UI_error_message("Var offset_x: " + offset_x[0] + ", " + offset_x[1] + ", " + offset_x[2] + ", " + offset_x[3] + ", " + offset_x[4] + ", " + offset_x[5] + ", " + offset_x[6] + ", " + offset_x[7] + ", " + offset_x[8] + ", " + offset_x[9] + ", " + offset_x[10] + ", " + offset_x[11]);
	UI_error_message("Var offset_y: " + offset_y[0] + ", " + offset_y[1] + ", " + offset_y[2] + ", " + offset_y[3] + ", " + offset_y[4] + ", " + offset_y[5] + ", " + offset_y[6] + ", " + offset_y[7] + ", " + offset_y[8] + ", " + offset_y[9] + ", " + offset_y[10] + ", " + offset_y[11]);
	UI_error_message("Var dist: " + dist);
	UI_error_message("Var counter: " + counter);

	UI_error_message("----------------------------------");


			while (counter != 12)
			{
				counter += 1;
				UI_error_message("Counter reads: " +counter);
		    	
				var find_x = findPos[0] + offset_x[counter];
    			var find_y = findPos[1] + offset_y[counter];
				
				var invisibles = findPos->find_nearby(SHAPE_ANY, dist, MASK_INVISIBLE);

			    for (obj in invisibles)
				{        
		        if (obj->get_item_flag(INVISIBLE) && !(obj in revealables))
					{
            		revealables &= obj;
        			}
    			}

			}


	item->set_npc_prop(MANA, -5);
	UI_error_message("Begin Animation and Effects");
	item_say("@Ort Lor@");
	script item
		{
			actor frame LEAN;
			wait 4;
			actor frame KNEEL;
			sfx 67;			
			wait 8;
			actor frame STAND;
		}
	
	UI_error_message("End Animation and Effects");

    if (revealables == [])
	    {
    	    UI_error_message("Var revealables: [] (empty array)");
    	} 
    		else
    		{
        		UI_error_message("Var revealables: " + revealables);
            	for (obj in revealables)
        		{
            		script obj after 5 ticks
            	{
                nohalt;
                call spellClearFlag, INVISIBLE;
            }
        obj->obj_sprite_effect(ANIMATION_GREEN_BUBBLES, -1, -1, 0, 0, 0, -1);
        }
    }

}

