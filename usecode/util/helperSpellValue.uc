//=========================//
// SPELL VALUE HELPERS     //
//=========================//

var spendMagicMana(var caster, var manaCost)
{
    var curMana = caster->get_npc_prop(MANA);
    UI_error_message("Mana before casting: " + curMana);

    if (curMana < manaCost)
    {
        caster->item_say("@Not enough mana...@");
        UI_error_message("Not enough mana to cast spell - return");
        return false;
    }

    caster->set_npc_prop(MANA, -manaCost);
    UI_error_message("Subtract " + manaCost + " from mana pool");
    return true;
}

// Sets an npc property to an absolute value - UI_set_npc_prop only adds its argument.
var setNpcPropAbsolute(var npc, var prop, var value)
{
    var current = npc->get_npc_prop(prop);
    UI_set_npc_prop(npc, prop, -current);
    UI_set_npc_prop(npc, prop, value);
    return value;
}

// Returns base plus a random signed offset in [-maxVariance, maxVariance].
var randomSpellDuration(var base, var maxVariance)
{
    var randomOffset = UI_get_random(maxVariance * 2 + 1) - (maxVariance + 1);
    return base + randomOffset;
}

// Returns a fixed spell duration with no variance.
var staticSpellDuration(var base)
{
    return base;
}