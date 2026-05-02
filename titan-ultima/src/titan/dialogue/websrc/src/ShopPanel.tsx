import { useEffect, useRef } from 'react';
import type { NPCFile, ShopItem } from './types';

interface ShopPanelProps {
  npc: NPCFile;
  open: boolean;
  onClose: () => void;
}

export function ShopPanel({ npc, open, onClose }: ShopPanelProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClose = () => onClose();
    dialog.addEventListener('close', handleClose);
    return () => dialog.removeEventListener('close', handleClose);
  }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClick = (e: MouseEvent) => {
      if (e.target === dialog) onClose();
    };
    dialog.addEventListener('click', handleClick);
    return () => dialog.removeEventListener('click', handleClick);
  }, [onClose]);

  const shopFunctions = Object.values(npc.functions).filter(
    (f) => f.type === 'shop' && f.shopItems && f.shopItems.length > 0
  );

  return (
    <dialog ref={dialogRef} className="look-dialog shop-dialog">
      <div className="look-modal shop-modal">
        <div className="look-modal-header">
          <h2 className="look-modal-title">
            <span className="look-icon">🛒</span>
            {npc.npc}&rsquo;s Shop
          </h2>
          <button className="btn btn-tiny look-close" onClick={onClose} type="button">✕</button>
        </div>
        <div className="look-modal-body">
          {shopFunctions.length === 0 && (
            <p className="look-empty">No shop items found.</p>
          )}
          {shopFunctions.map((func) => (
            <div key={func.name} className="shop-section">
              <h4 className="shop-section-title">{func.name}</h4>
              <table className="shop-table">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Price</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {(func.shopItems ?? []).map((item: ShopItem, i: number) => (
                    <tr key={`${func.name}-${i}`}>
                      <td className="shop-item-name">{item.name}</td>
                      <td className="shop-item-price">
                        {item.price != null ? `${item.price} obs` : '—'}
                      </td>
                      <td className="shop-item-desc">{item.description ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </div>
    </dialog>
  );
}
