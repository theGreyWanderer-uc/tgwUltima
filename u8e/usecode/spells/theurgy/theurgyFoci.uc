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
		UI_error_message("curMana function eval using -caster->get_npc_prop(MANA)- eval before running proc:" + curMana); 


		if (theurgyFrame == 0)  //theurgyHealingTouch
		{
			UI_error_message("Frame 0 Detected - Spell Execution Start");
			AVATAR->theurgyHealingTouch();
			UI_error_message("Spell Execution Finished");
		}
		else if (theurgyFrame == 2)  //theurgyRestoration
		{
			UI_error_message("Frame 2 Detected - Spell Execution Start");
			AVATAR->theurgyRestoration();
			UI_error_message("Spell Execution Finished");
		}
		
	}
}