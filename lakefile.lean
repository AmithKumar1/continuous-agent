import Lake
open Lake DSL

package «continuous_agent» where

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git"

@[default_target]
lean_lib «ContinuousAgent» where
