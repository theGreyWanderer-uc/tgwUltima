import { useEffect, useMemo, useRef, useState } from 'react';
import { useWorldState } from './store';
import { evaluateLook } from './engine';
import type { ItemProperties, NPCFile, OverlayProperties } from './types';

interface LookPanelProps {
  npc: NPCFile;
  open: boolean;
  onClose: () => void;
  onOpenFlags: () => void;
}

const STYLE_ICONS: Record<string, string> = {
  sword: '🗡',
  blunt: '🔨',
  axe: '🪓',
  dagger: '🗡',
};

function OverlayInfo({ overlay }: { overlay: OverlayProperties }) {
  const icon = STYLE_ICONS[overlay.animationStyle] ?? '⚔';
  return (
    <div className="item-stats">
      <div className="item-stats-section">
        <h3 className="item-stats-heading">{icon} Weapon Overlay ({overlay.animationStyle})</h3>
        <p className="overlay-description">
          Combat animation sprite used by:
        </p>
        <ul className="overlay-weapon-list">
          {overlay.usedBy.map(w => <li key={w}>{w}</li>)}
        </ul>
      </div>
    </div>
  );
}

function ItemStats({ properties }: { properties: ItemProperties }) {
  const { weapon, armour, overlay } = properties;
  if (overlay) return <OverlayInfo overlay={overlay} />;
  return (
    <div className="item-stats">
      {weapon && (
        <div className="item-stats-section">
          <h3 className="item-stats-heading">
            {weapon.isSpecial ? '⚔ Special Weapon' : '⚔ Weapon'}
          </h3>
          <table className="item-stats-table">
            <tbody>
              <tr>
                <td className="item-stats-label">Base Damage</td>
                <td className="item-stats-value">{weapon.baseDamage}</td>
              </tr>
              <tr>
                <td className="item-stats-label">Damage Modifier</td>
                <td className="item-stats-value">{weapon.damageModifier}</td>
              </tr>
              <tr>
                <td className="item-stats-label">Damage Type</td>
                <td className="item-stats-value">
                  {weapon.damageType.map(t => (
                    <span key={t} className={`dmg-tag dmg-${t}`}>{t}</span>
                  ))}
                </td>
              </tr>
              {weapon.attackDexBonus > 0 && (
                <tr>
                  <td className="item-stats-label">Attack DEX Bonus</td>
                  <td className="item-stats-value">+{weapon.attackDexBonus}</td>
                </tr>
              )}
              {weapon.defendDexBonus > 0 && (
                <tr>
                  <td className="item-stats-label">Defend DEX Bonus</td>
                  <td className="item-stats-value">+{weapon.defendDexBonus}</td>
                </tr>
              )}
              {weapon.armourBonus > 0 && (
                <tr>
                  <td className="item-stats-label">Armour Bonus</td>
                  <td className="item-stats-value">+{weapon.armourBonus}</td>
                </tr>
              )}
              {weapon.treasureChance != null && (
                <tr>
                  <td className="item-stats-label">Treasure Chance</td>
                  <td className="item-stats-value">{weapon.treasureChance}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {armour && (
        <div className="item-stats-section">
          <h3 className="item-stats-heading">🛡 Armour</h3>
          <table className="item-stats-table">
            <tbody>
              <tr>
                <td className="item-stats-label">Armour Class</td>
                <td className="item-stats-value">{armour.armourClass}</td>
              </tr>
              {armour.defenseType && (
                <tr>
                  <td className="item-stats-label">Defense Type</td>
                  <td className="item-stats-value">
                    {armour.defenseType.map(t => (
                      <span key={t} className={`dmg-tag dmg-${t}`}>{t}</span>
                    ))}
                  </td>
                </tr>
              )}
              {armour.kickBonus != null && armour.kickBonus > 0 && (
                <tr>
                  <td className="item-stats-label">Kick Bonus</td>
                  <td className="item-stats-value">+{armour.kickBonus}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function LookPanel({ npc, open, onClose, onOpenFlags }: LookPanelProps) {
  const { flags, npcIndex } = useWorldState();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [deadMode, setDeadMode] = useState<'alive' | 'dead'>('alive');

  // Sync the native <dialog> open state with the `open` prop
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  // Reset runtime state whenever a new NPC look modal is opened.
  useEffect(() => {
    if (open) setDeadMode('alive');
  }, [npc.npc, open]);

  // Handle native close event (Escape key)
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClose = () => onClose();
    dialog.addEventListener('close', handleClose);
    return () => dialog.removeEventListener('close', handleClose);
  }, [onClose]);

  // Close on backdrop click
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClick = (e: MouseEvent) => {
      if (e.target === dialog) onClose();
    };
    dialog.addEventListener('click', handleClick);
    return () => dialog.removeEventListener('click', handleClick);
  }, [onClose]);

  const descriptions = useMemo(
    () => evaluateLook(npc, flags, { deadMode }, npcIndex),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [npc.npc, flags, deadMode, npcIndex]
  );
  const active = descriptions.filter(d => d.active);
  const hasDeadCondition = descriptions.some(d => d.requiresDead);

  return (
    <dialog ref={dialogRef} className="look-dialog">
      <div className="look-modal">
        <div className="look-modal-header">
          <h2 className="look-modal-title">
            <span className="look-icon">👁</span>
            Look: {npc.npc}
          </h2>
          <div className="look-modal-header-actions">
            <button
              className="btn btn-tiny"
              title="Open Global Flags"
              aria-label="Open Global Flags"
              onClick={onOpenFlags}
              type="button"
            >
              ⚑
            </button>
            <button className="btn btn-tiny look-close" onClick={onClose} type="button">✕</button>
          </div>
        </div>

        <div className="look-modal-body">
          {npc.itemProperties && <ItemStats properties={npc.itemProperties} />}

          {hasDeadCondition && (
            <div className="look-runtime-controls">
              <span className="look-runtime-label">Runtime:</span>
              <button
                className={`btn btn-tiny ${deadMode === 'alive' ? 'btn-primary' : ''}`}
                onClick={() => setDeadMode('alive')}
                type="button"
              >
                Alive
              </button>
              <button
                className={`btn btn-tiny ${deadMode === 'dead' ? 'btn-primary' : ''}`}
                onClick={() => setDeadMode('dead')}
                type="button"
              >
                Dead
              </button>
            </div>
          )}

          {descriptions.length === 0 ? (
            <p className="look-empty">No look description available.</p>
          ) : (
            <>
              {active.length > 0 && (
                <div className="look-active-card">
                  <div className="look-badges">
                    <span className="look-badge look-badge-active">Active</span>
                    {active.flatMap(d => d.flagNames).filter(Boolean).map(f => (
                      <span key={f} className="look-badge look-badge-flag">{f}</span>
                    ))}
                  </div>
                  <p className="look-active-text">{active.map(d => d.text).join(' ')}</p>
                </div>
              )}

              <div className="look-all-section">
                <h3 className="look-all-heading">All Possible Descriptions</h3>
                {descriptions.map((d, idx) => (
                  <div key={`${d.text}-${idx}`} className={`look-card ${!d.active ? 'look-card-dimmed' : ''}`}>
                    {d.flagNames.length > 0 && (
                      <div className="look-badges">
                        {d.flagNames.map(f => (
                          <span key={f} className="look-badge look-badge-flag">Requires: {f}</span>
                        ))}
                        {d.requiresDead && (
                          <span className="look-badge look-badge-flag">Requires: Dead</span>
                        )}
                      </div>
                    )}
                    {d.condition && d.flagNames.length === 0 && !d.requiresDead && (
                      <div className="look-badges">
                        <span className="look-badge look-badge-flag">{d.condition}</span>
                      </div>
                    )}
                    {d.requiresDead && d.flagNames.length === 0 && (
                      <div className="look-badges">
                        <span className="look-badge look-badge-flag">Requires: Dead</span>
                      </div>
                    )}
                    <p className="look-card-text">{d.text}</p>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </dialog>
  );
}
