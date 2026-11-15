import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { AITool, Preset, Recipe } from '../api/types';
import { cloneRecipe } from '../lib/recipe';

export interface RecipeState {
  recipe: Recipe | null;
  presets: Preset[];
  presetId: string;
  edit: (mutate: (draft: Recipe) => void) => void;
  setAI: (tool: AITool, on: boolean) => void;
  selectPreset: (id: string) => void;
  reloadPresets: () => Promise<Preset[]>;
  savePreset: (name: string) => Promise<Preset>;
  resetTo: (recipe: Recipe) => void;
}

// The recipe is shared intent only: it never carries sky regions, label regions or masks (those belong to each asset).
export function useRecipe(onError: (err: unknown) => void): RecipeState {
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);

  const reloadPresets = useCallback(async () => {
    const list = (await api.listPresets()).presets;
    setPresets(list);
    return list;
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.listPresets().then(
      ({ presets: list }) => {
        if (cancelled) return;
        setPresets(list);
        const natural = list.find((p) => p.id === 'natural' && p.recipe) ?? list.find((p) => p.compatible && p.recipe);
        if (natural?.recipe) setRecipe({ ...cloneRecipe(natural.recipe), preset: natural.id });
      },
      onError,
    );
    return () => {
      cancelled = true;
    };
  }, [onError]);

  const edit = useCallback((mutate: (draft: Recipe) => void) => {
    setRecipe((prev) => {
      if (!prev) return prev;
      const next = cloneRecipe(prev);
      mutate(next);
      next.preset = 'custom';
      return next;
    });
  }, []);

  const selectPreset = useCallback(
    (id: string) => {
      if (id === 'custom') {
        setRecipe((prev) => (prev ? { ...prev, preset: 'custom' } : prev));
        return;
      }
      const p = presets.find((x) => x.id === id);
      // Built-in presets describe a look; the AI tool switches stay as the user set them. Saved presets bring their own.
      if (p?.recipe && p.compatible) {
        const next = p.recipe;
        setRecipe((prev) => ({ ...cloneRecipe(next), preset: p.id, ai: p.builtin && prev ? { ...prev.ai } : { ...next.ai } }));
      }
    },
    [presets],
  );

  const savePreset = useCallback(
    async (name: string) => {
      if (!recipe) throw new Error('Settings are still loading.');
      const created = await api.createPreset(name, recipe);
      await reloadPresets();
      if (created.recipe) setRecipe({ ...cloneRecipe(created.recipe), preset: created.id });
      return created;
    },
    [recipe, reloadPresets],
  );

  const setAI = useCallback((tool: AITool, on: boolean) => {
    setRecipe((prev) => (prev ? { ...prev, ai: { ...prev.ai, [tool]: on } } : prev));
  }, []);

  const resetTo = useCallback((r: Recipe) => setRecipe(cloneRecipe(r)), []);

  return { recipe, presets, presetId: recipe?.preset ?? 'natural', edit, setAI, selectPreset, reloadPresets, savePreset, resetTo };
}
