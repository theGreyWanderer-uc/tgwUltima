//theurgyFoci.uc
//handle Theurgy Spell Foci Double Clicks

void theurgyFoci shape#(1058) ()

{
    if (event == DOUBLECLICK){
		UI_error_message("Attempted Double Click of Shape 1058");

		UI_error_message("Attempt to close gumps");
		UI_close_gumps();
		UI_error_message("Gumps should be closed");
		
		//get frame of theurgyFoci
		var theurgyFrame = UI_get_item_frame(item);
		var outFrameMessage = "Shape 1058 Frame is " + theurgyFrame;

		UI_error_message(outFrameMessage);
		UI_error_message("Try to match desired frame");

		var caster = getOuterContainer(item);
		UI_error_message("caster variable getOuterContainer(item) content:" + caster); 		
		var curMana = caster->get_npc_prop(MANA);
		UI_error_message("curMana function eval using -caster->get_npc_prop(MANA)- eval before running proc: " + curMana); 

		if (theurgyFrame == 0)  //theurgyHealingTouch
		{
			UI_error_message("Frame 0 Detected - Spell Execution Start");
			item->theurgyHealingTouch();
			UI_error_message("Spell Execution Finished");
		}
		
		else if (theurgyFrame == 2)  //theurgyRestoration
		{
			UI_error_message("Frame 2 Detected - Spell Execution Start");
			AVATAR->theurgyRestoration();
			UI_error_message("Spell Execution Finished");
		}

		else if (theurgyFrame == 4)  //theurgyReveal
		{
			UI_error_message("Frame 4 Detected - Spell Execution Start");
			AVATAR->theurgyReveal();
			UI_error_message("Spell Execution Finished");
		}

		else if (theurgyFrame == 6)  //theurgyFadeFromSight
		{
			UI_error_message("Frame 6 Detected - Spell Execution Start");
			AVATAR->theurgyFadeFromSight();
			UI_error_message("Spell Execution Finished");
		}		

		else if (theurgyFrame == 8)  //theurgyDivination
		{
			UI_error_message("Frame 8 Detected - Spell Execution Start");
			AVATAR->theurgyDivination();
			UI_error_message("Spell Execution Finished");
		}		

		else if (theurgyFrame == 14)  //theurgyAirWalk
		{
			UI_error_message("Frame 14 Detected - Spell Execution Start");
			AVATAR->theurgyAirWalk();
			UI_error_message("Spell Execution Finished");
		}

		else if (theurgyFrame == 15)  //theurgyObjectDebugger
		{
			UI_error_message("Frame 15 Detected - Spell Execution Start");
			var caster = getOuterContainer(item);
        	caster->theurgyObjectDebugger();
			UI_error_message("Spell Execution Finished");
		}



	}
}
