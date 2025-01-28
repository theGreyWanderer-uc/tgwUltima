void theurgyDivination object#() () {

	var quality = UI_get_item_quality(item);
	var frame = UI_get_item_frame(item);

	UI_error_message("theurgyDivination executing");

	var day = UI_game_day();
	UI_error_message("day value: " +day);
		if (day == 1) {
	        day = "First day";
	    } else if (day == 2) {
        	day = "Second day";
    	} else if (day == 3) {
	        day = "Third day";
	    } else if (day == 4) {
        	day = "Fourth day";
    	} else if (day == 5) {
	        day = "Fifth day";
	    } else if (day == 6) {
        	day = "Sixth day";
    	} else if (day == 7) {
	        day = "Seventh day";
	    } else {
        	day = "Unknown Day";  //for when we move to Pagan days
    	}

	var hour = UI_game_hour();
	UI_error_message("hour value: " +hour);
	var meridiem;
		if (hour < 12)
		{
			meridiem  = "am";
		} else
		{
		meridiem  = "pm";
		}
	var minute = UI_game_minute();
		if (minute < 10)
		{
		minute = "0" + minute;
		}
		
		hour %= 12;
		if (hour == 0)
		{
		hour = 12;
		}
	UI_error_message("meridiem value: " +meridiem);

	var partDay = UI_part_of_day();
	UI_error_message("Part of day int value: " +partDay);
    	if (partDay == 0) {
	        partDay = "Midnight";
	    } else if (partDay == 1) {
        	partDay = "Early Morning";
    	} else if (partDay == 2) {
	        partDay = "Dawn";
	    } else if (partDay == 3) {
        	partDay = "Morning";
    	} else if (partDay == 4) {
	        partDay = "Noon";
	    } else if (partDay == 5) {
        		partDay = "Afternoon";
    	} else if (partDay == 6) {
	        partDay = "Evening";
	    } else if (partDay == 7) {
        	partDay = "Night";
    	} else {
	        partDay = "Unknown Time"; //for when we move to Pagan time
	    }
	UI_error_message("Part of day updated string value: " +partDay);		
	

		//var dateTime = day + " " + hour + ":" + minute + " " + meridiem;
	var dateTime = "It is currently " + hour + ":" + minute + " " + meridiem;
	UI_error_message("theurgyDivination check dateTime: " + dateTime);
	var dateMeridiem = partDay + " on the " + day;
	UI_error_message("theurgyDivination check dateMeridiem: " + dateMeridiem);
	var divMessage1 = dateTime + " " + dateMeridiem;
	UI_error_message("theurgyDivination check divMessage1: " + divMessage1);


	var caster = getOuterContainer(item);
	var curMana = get_npc_prop(MANA);
	UI_error_message("curMana proc eval using -get_npc_prop(MANA) - before checking:" + curMana); 
    
		if (curMana < 3)
		{
			var curMana = get_npc_prop(MANA);
			item_say("@Not enough mana...@");
			var curManaMessage = "curMana proc eval using -get_npc_prop- while failing check:" + curMana;
			UI_error_message(curManaMessage);
			UI_error_message("Not enough mana to cast spell - return");
			return;
		}        

	item->set_npc_prop(MANA, -3);
	UI_error_message("Begin Animation and Effects");
	item_say("@In Wis@");
	script item
		{
			actor frame LEAN;
			wait 4;
			actor frame KNEEL;
			sfx 67;			
			wait 8;
			actor frame STAND;
		}
	
	delayedBark(AVATAR, dateTime, 20);
	delayedBark(AVATAR, dateMeridiem, 35);

	delayedBark(DUPRE, "@Magic that sucker, yeah!@", 50);
	delayedBark(IOLO, "@Hell of a trick Avatar!@", 65);
	
	UI_error_message("End Animation and Effects");

}
