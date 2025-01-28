void theurgyRestoration object#() () {

var quality = UI_get_item_quality(item);
var frame = UI_get_item_frame(item);

UI_error_message("theurgyRestoration executing");

var caster = getOuterContainer(item);
var curMana = caster->get_npc_prop(MANA);
UI_error_message("curMana proc eval using -caster->get_npc_prop(MANA)- eval before checking:" + curMana); 
var curMana2 = get_npc_prop(MANA);
UI_error_message("curMana2 proc eval using -get_npc_prop(MANA)- eval before checking:" + curMana2); 
    
	if (curMana2 < 15)
	{
		var curMana = get_npc_prop(MANA);
		item_say("@Not enough mana...@");
		var curManaMessage = "curMana proc eval using -get_npc_prop- while failing check:" + curMana;
		UI_error_message(curManaMessage);
		UI_error_message("Not enough mana to cast spell - return");
		return;
	}        

	var target = UI_click_on_item();
	target->halt_scheduled();

		if (target->is_npc())
		{
			UI_error_message("target is NPC");
			var dir = direction_from(target);
			var str = target->get_npc_prop(STRENGTH);
			var hps = target->get_npc_prop(HEALTH);
			var maxheal = str - hps;

				if (maxheal <= 0)
				{
					item_say("@They are already in perfect health!@");
					UI_error_message("Target does not need healing - return");
					return;
				}

				item->set_npc_prop(MANA, -15);
				UI_error_message("Subtract 15 from mana pool");
				
				UI_error_message("Begin Animation and Effects");
				if (hps <= str)
				{
					item_say("@In Vas Mani@");
					
					script item
					{
						nohalt;
						face dir;
						actor frame reach_1h;
						actor frame raise_1h;
						actor frame strike_1h;
						sfx 64;					
					}
					
				UI_error_message("End Animation and Effects");
				var healquant = 50;

					if (healquant > maxheal)
					{
						healquant = maxheal;
					}
					
					target->set_npc_prop(HEALTH, healquant);
					UI_error_message("Attempted to heal target for: " + healquant);
				}
		} else {
			UI_error_message("Attempted to heal an invalid target.");
			item_say("@I cannot heal that!@");
			}
}