# python train.py \
#          --epochs 7 \
#          --dataset MaskSplitStratifyDataset \
#          --label mask\
#          --augmentation get_transforms \
#          --resize 384 256 \
#          --lr 0.00003 \
#          --lr_decay_step 50 \
#          --lr_gamma 0.5 \
#          --batch_size 16 \
#          --valid_batch_size 32 \
#          --model EfficientNet \
#          --model_version tf_efficientnet_b7\
#          --optimizer Adam \
#          --criterion focal\
#          --log_interval 100\
#          --name T2065/EfficientNet_b7_focal_0902_mask

        
# python train.py \
#          --epochs 7 \
#          --dataset MaskSplitStratifyDataset \
#          --label gender\
#          --augmentation get_transforms \
#          --resize 384 256 \
#          --lr 0.00003 \
#          --lr_decay_step 50 \
#          --lr_gamma 0.5 \
#          --batch_size 16 \
#          --valid_batch_size 32 \
#          --model EfficientNet \
#          --model_version tf_efficientnet_b7\
#          --optimizer Adam \
#          --criterion focal\
#          --log_interval 100\
#          --name T2065/EfficientNet_b7_focal_0902_gender

python train.py \
         --epochs 5 \
         --dataset MaskSplitStratifyDataset \
         --label age\
         --augmentation get_transforms \
         --resize 384 256 \
         --lr 0.00003 \
         --lr_decay_step 50 \
         --lr_gamma 0.5 \
         --batch_size 16 \
         --valid_batch_size 32 \
         --model EfficientNet \
         --model_version tf_efficientnet_b7\
         --optimizer Adam \
         --criterion focal_smoothing\
         --log_interval 100\
         --name T2065/EfficientNet_b7_focal_0902_age
